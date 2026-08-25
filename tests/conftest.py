"""Shared fixtures and a synthetic application contract for tests."""

import json
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest

from mappings.core import CORE_FIELD_MAPPINGS
from mappings.semantic import SEMANTIC_FIELD_APPROVALS
from pipeline.dataset_contract import TABLE_COLUMN_COUNTS
from pipeline.normalize.type_rules import build_typed_rule
from pipeline.structured.schema import build_staging_schema

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


_TEST_RUNTIME_DIRECTORY: TemporaryDirectory[str] | None = None


def _write_synthetic_runtime_schema(directory: Path) -> Path:
    """Write a 280-column test-only schema without claiming G1 evidence."""

    declared_types: dict[tuple[str, str], str] = {}
    target_to_declared = {
        "TEXT": "text",
        "DECIMAL": "numeric",
        "INTEGER": "bigint",
        "DATE": "date",
        "TIMESTAMP": "timestamp without time zone",
    }
    for mapping in CORE_FIELD_MAPPINGS:
        declared_types[(mapping.logical_table_id, mapping.source_column)] = (
            target_to_declared[mapping.target_type]
        )
    for approval in SEMANTIC_FIELD_APPROVALS:
        identity = (approval.logical_table_id, approval.source_column)
        declared_types.setdefault(
            identity,
            (
                "text"
                if approval.source_column in {"pd_itm_no", "pd_nm"}
                else "numeric"
            ),
        )

    names_by_table: dict[str, list[str]] = defaultdict(list)
    for table_id, source_column in declared_types:
        names_by_table[table_id].append(source_column)

    rules = []
    for table_id, expected_count in TABLE_COLUMN_COUNTS.items():
        source_names = names_by_table[table_id]
        if len(source_names) > expected_count:
            raise RuntimeError(f"test semantic fields exceed {table_id} physical shape")
        for index in range(len(source_names) + 1, expected_count + 1):
            source_names.append(f"synthetic_contract_field_{index:03d}")
        for source_column in source_names:
            rules.append(
                build_typed_rule(
                    logical_table_id=table_id,
                    source_column=source_column,
                    declared_type=declared_types.get(
                        (table_id, source_column),
                        "text",
                    ),
                )
            )

    schema = build_staging_schema(rules)
    report_path = directory / "synthetic_g2b_structured_schema.json"
    report_path.write_text(
        json.dumps(
            {
                "g2b_format_version": "1.0",
                "schema_status": "PASS",
                "storage": schema.to_dict(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path


def pytest_sessionstart(session: pytest.Session) -> None:
    """Point module-level application composition at an explicit test schema."""

    del session
    global _TEST_RUNTIME_DIRECTORY
    _TEST_RUNTIME_DIRECTORY = TemporaryDirectory(prefix="mirae-test-runtime-")
    report_path = _write_synthetic_runtime_schema(
        Path(_TEST_RUNTIME_DIRECTORY.name)
    )
    import app.composition as composition

    composition._DEFAULT_G2B_STRUCTURED_SCHEMA_PATH = report_path


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int,
) -> None:
    """Release the test-only runtime schema after the complete session."""

    del session, exitstatus
    if _TEST_RUNTIME_DIRECTORY is not None:
        _TEST_RUNTIME_DIRECTORY.cleanup()


@pytest.fixture
def client() -> Iterator["TestClient"]:
    """Run each test against the application, including its lifespan hooks."""

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
