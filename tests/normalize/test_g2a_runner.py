"""Synthetic E2E proof for the read-only G2-A report contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import mappings.concepts.registry as concept_registry
import pipeline.normalize.runner as g2a_runner
import pipeline.profiling.runner as g1_runner
from pipeline.normalize.constants import G2A_REPORT_FILENAMES
from pipeline.profiling import run_profiling
from pipeline.profiling.constants import TableSpec


def _snapshots(paths: tuple[Path, ...]) -> dict[Path, tuple[bytes, str, int]]:
    """Capture all three immutability dimensions required by the contract."""

    result: dict[Path, tuple[bytes, str, int]] = {}
    for path in paths:
        content = path.read_bytes()
        result[path] = (
            content,
            hashlib.sha256(content).hexdigest(),
            path.stat().st_mtime_ns,
        )
    return result


def _synthetic_table_specs() -> dict[str, TableSpec]:
    return {
        "PRBD01N001": TableSpec("PRBD01N001", "synthetic", 2),
        "PREF01N001": TableSpec("PREF01N001", "synthetic", 2),
        "PREF02N001": TableSpec("PREF02N001", "synthetic", 2),
        "PRFD01N001": TableSpec(
            "PRFD01N001",
            "synthetic",
            2,
            physical_id_aliases=("PRFDN001",),
        ),
    }


def test_run_g2a_writes_exactly_five_reports_without_mutating_inputs(
    synthetic_g2a_sources: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Run the real orchestrator with only its official counts test-patched.

    Production keeps the hard 207-column/145,393-row checks.  This test replaces
    those constants only inside the temporary process so the same orchestration
    can be exercised over eight synthetic columns and eight synthetic rows.
    """

    synthetic_specs = _synthetic_table_specs()
    monkeypatch.setattr(g1_runner, "TABLE_SPECS", synthetic_specs)
    monkeypatch.setattr(g1_runner, "EXPECTED_TOTAL_ROWS", 8)
    monkeypatch.setattr(g2a_runner, "EXPECTED_COVERAGE_COLUMN_COUNT", 8)
    monkeypatch.setattr(g2a_runner, "EXPECTED_TOTAL_ROWS", 8)
    monkeypatch.setattr(concept_registry, "_OFFICIAL_COLUMN_COUNT", 8)

    source_before = _snapshots(synthetic_g2a_sources.all_paths)
    g1_report_dir = tmp_path / "g1-reports"
    g1_result = run_profiling(
        synthetic_g2a_sources.raw_dir,
        synthetic_g2a_sources.schema_dir,
        g1_report_dir,
    )
    assert g1_result["status"] == "PASS"
    assert _snapshots(synthetic_g2a_sources.all_paths) == source_before

    g1_paths = tuple(sorted(path for path in g1_report_dir.iterdir() if path.is_file()))
    assert len(g1_paths) == 5
    g1_before = _snapshots(g1_paths)
    output_dir = tmp_path / "g2a-reports"

    result = g2a_runner.run_g2a(
        synthetic_g2a_sources.raw_dir,
        synthetic_g2a_sources.schema_dir,
        g1_report_dir,
        output_dir,
    )

    assert result["status"] == "PASS"
    assert result["source_file_count"] == 8
    assert result["source_row_count"] == 8
    assert result["rule_count"] == 8
    assert result["coverage_column_count"] == 8
    assert result["coverage_ratio"] == 1.0
    assert result["sources_unchanged"] is True
    assert result["g1_reports_unchanged"] is True
    assert tuple(result["report_paths"]) == G2A_REPORT_FILENAMES
    assert {path.name for path in output_dir.iterdir()} == set(G2A_REPORT_FILENAMES)
    assert _snapshots(synthetic_g2a_sources.all_paths) == source_before
    assert _snapshots(g1_paths) == g1_before

    lineage = json.loads(
        (output_dir / "g2a_lineage_summary.json").read_text(encoding="utf-8")
    )
    pref01_review = lineage["pref01_declared_key_blank_review"]
    assert pref01_review["empty_count"] == 1
    assert pref01_review["declared_key_rows_with_any_blank"] == 1
    assert pref01_review["business_primary_key_enforced"] is False
    assert pref01_review["review_status"] == "NOT_NULL_BUSINESS_KEY_BLOCKED"

    report_text = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.iterdir()
    )
    for raw_value in (
        "SYNTHETIC_ALPHA",
        "SYNTHETIC_MARKET",
        "SYNTHETIC_EPSILON",
    ):
        assert raw_value not in report_text
