"""Opt-in G2-B Live Structured Query Validation against the real, already
loaded PostgreSQL staging database.

Unlike ``test_postgres_structured.py`` (which creates its own disposable
temporary table under a *separate* ``G2B_TEST_DATABASE_URL``), this test
deliberately targets the SAME ``DATABASE_URL`` the application and the G2-B
loader already use, because the goal is to validate staging tables for the
active official dataset contract -- not a synthetic fixture.

This test never loads, replaces, inserts, updates, or deletes anything. It
only builds a read-only ``TrustedQueryRegistry`` from the existing G1/G2-A
reports already on disk (no re-scan of the source workbooks is required
because those reports are themselves immutable, checksum-verified inputs),
and then calls ``run_live_query_validation``, which issues SELECT-only
statements through the real production path and an independent read-only
oracle.

Skipped automatically when ``DATABASE_URL`` is not configured, so a normal
``pytest`` run (and CI) is unaffected. It never prints or asserts on the
connection string itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.structured.registry import build_trusted_query_registry
from mappings.core import CORE_FIELD_MAPPINGS
from pipeline.normalize.scanner import build_rules_from_profiles
from pipeline.structured.live_validation import run_live_query_validation
from pipeline.structured.schema import build_staging_schema


DATABASE_URL = os.getenv("DATABASE_URL")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_G1_DIR = _REPO_ROOT / "outputs" / "reports" / "g1"
_DEFAULT_G2A_DIR = _REPO_ROOT / "outputs" / "reports" / "g2a"
G1_REPORT_DIR = Path(os.getenv("G1_REPORT_DIR", str(_DEFAULT_G1_DIR)))
G2A_REPORT_DIR = Path(os.getenv("G2A_REPORT_DIR", str(_DEFAULT_G2A_DIR)))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_real_registry():
    schema_profile = _read_json(G1_REPORT_DIR / "g1_schema_profile.json")
    data_profile = _read_json(G1_REPORT_DIR / "g1_data_profile.json")
    rules = tuple(build_rules_from_profiles(schema_profile, data_profile))
    schema = build_staging_schema(rules)
    return build_trusted_query_registry(schema, CORE_FIELD_MAPPINGS)


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is not configured; live validation cannot reach PostgreSQL",
)
@pytest.mark.skipif(
    not (_DEFAULT_G1_DIR / "g1_schema_profile.json").is_file() and "G1_REPORT_DIR" not in os.environ,
    reason="G1/G2-A report directory was not found next to the repository root",
)
def test_live_query_validation_passes_against_the_real_staging_tables() -> None:
    import psycopg

    registry = _build_real_registry()

    def connection_factory():
        # connect_timeout keeps a misconfigured/unreachable host from hanging
        # the whole suite; autocommit avoids leaving any implicit
        # transaction open across the SELECT-only calls this module makes.
        connection = psycopg.connect(DATABASE_URL, connect_timeout=5)
        connection.autocommit = True
        return connection

    result = run_live_query_validation(connection_factory, registry)

    assert result["query_values_copied_to_report"] is False
    for name, shape in result["shapes"].items():
        assert shape["status"] == "PASS", (name, shape["reason"], shape["checks"])
    assert result["parse_status_gate"]["status"] in {"PASS", "NOT_APPLICABLE"}
    assert result["status"] == "PASS"
