"""End-to-end G1 profiler tests using only temporary synthetic workbooks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.profiling import run_profiling
from pipeline.profiling.discovery import DiscoveryError


REPORT_FILENAMES = {
    "g1_file_manifest.json",
    "g1_schema_profile.json",
    "g1_data_profile.json",
    "g1_schema_diff.json",
    "g1_summary.md",
}
RESULT_KEYS = {
    "status",
    "file_count",
    "logical_table_count",
    "expected_total_rows",
    "observed_total_rows",
    "sources_unchanged",
    "report_paths",
}


def _source_snapshot(paths: tuple[Path, ...]) -> dict[Path, tuple[bytes, str, int]]:
    snapshots: dict[Path, tuple[bytes, str, int]] = {}
    for path in paths:
        content = path.read_bytes()
        snapshots[path] = (
            content,
            hashlib.sha256(content).hexdigest(),
            path.stat().st_mtime_ns,
        )
    return snapshots


def _load_json(output_dir: Path, filename: str) -> dict[str, Any]:
    return json.loads((output_dir / filename).read_text(encoding="utf-8"))


def _table(document: dict[str, Any], table_id: str) -> dict[str, Any]:
    return next(
        table
        for table in document["tables"]
        if table["logical_table_id"] == table_id
    )


def _column(table: dict[str, Any], qualified_name: str) -> dict[str, Any]:
    return next(
        column
        for column in table["columns"]
        if column["qualified_name"] == qualified_name
    )


def test_run_profiling_reports_quality_evidence_without_mutating_sources(
    synthetic_workbooks,
    tmp_path: Path,
) -> None:
    # Preamble has partial overlap; the real header has the strongest exact
    # schema overlap. Data order also deliberately differs from the schema.
    synthetic_workbooks.write_schema(
        "PRBD01N001",
        fields=["field_a", "field_b", "field_c"],
        preamble=[["synthetic schema note"]],
        examples={"field_a": "SCHEMA_SAMPLE_MUST_NOT_LEAK"},
    )
    synthetic_workbooks.write_data(
        "PRBD01N001",
        preamble=[["field_a", "synthetic data note"]],
        headers=["field_b", "field_a", "field_extra"],
        rows=[
            [None, "alpha", "extra-1"],
            ["", "beta", "extra-2"],
            ["   ", "gamma", "extra-3"],
            [7, "delta", "extra-4"],
        ],
        trailing_blank_rows=2,
    )

    # Duplicate headers must remain distinct by occurrence in both schema and
    # data profiles rather than being collapsed in a dict.
    synthetic_workbooks.write_schema(
        "PREF01N001",
        fields=["field_a", "field_a", "field_b"],
    )
    synthetic_workbooks.write_data(
        "PREF01N001",
        headers=["field_a", "field_a", "field_b"],
        rows=[["first", "x", 1], ["second", None, 2]],
    )

    # Formula and merged-cell structure are evidence, not values to evaluate.
    synthetic_workbooks.write_data(
        "PREF02N001",
        headers=["field_a", "field_b"],
        rows=[["formula-row", "=1+1"]],
        merged_ranges=("A4:B4",),
    )

    # An integer date-shape candidate is true only when every observed integer
    # is an eight-digit, valid calendar date.
    synthetic_workbooks.write_schema(
        "PRFD01N001",
        fields=["all_valid_dates", "mixed_integers"],
    )
    synthetic_workbooks.write_data(
        "PRFD01N001",
        headers=["all_valid_dates", "mixed_integers"],
        rows=[
            [20260101, 20260101],
            [20260228, 12345678],
            [20261231, 20260230],
        ],
    )

    before = _source_snapshot(synthetic_workbooks.all_paths)
    output_dir = tmp_path / "reports"

    result = run_profiling(
        synthetic_workbooks.raw_dir,
        synthetic_workbooks.schema_dir,
        output_dir,
    )

    assert set(result) == RESULT_KEYS
    assert result["file_count"] == 8
    assert result["logical_table_count"] == 4
    assert result["observed_total_rows"] == 10
    assert result["sources_unchanged"] is True
    # Synthetic row counts intentionally cannot satisfy official G1 counts.
    assert result["status"] == "FAIL"
    assert set(result["report_paths"]) == REPORT_FILENAMES
    assert {
        Path(report_path).name for report_path in result["report_paths"].values()
    } == REPORT_FILENAMES
    assert all(
        Path(report_path).is_file()
        for report_path in result["report_paths"].values()
    )
    assert {path.name for path in output_dir.iterdir()} == REPORT_FILENAMES
    assert _source_snapshot(synthetic_workbooks.all_paths) == before

    manifest = _load_json(output_dir, "g1_file_manifest.json")
    schema_profile = _load_json(output_dir, "g1_schema_profile.json")
    data_profile = _load_json(output_dir, "g1_data_profile.json")
    schema_diff = _load_json(output_dir, "g1_schema_diff.json")

    assert manifest["sources_immutable"] is True
    assert data_profile["source_rows_copied"] is False
    assert data_profile["arbitrary_value_samples_copied"] is False
    assert data_profile["bounded_aggregate_evidence_included"] is True
    assert len(manifest["files"]) == 8
    assert all(entry["source_immutable"] for entry in manifest["files"])
    fund_raw = next(
        entry
        for entry in manifest["files"]
        if entry["logical_table_id"] == "PRFD01N001"
        and entry["source_kind"] == "datarows"
    )
    assert fund_raw["physical_filename"].startswith("PRFDN001_")

    prbd_data = _table(data_profile, "PRBD01N001")
    assert prbd_data["selected_data_sheet"] == "datarows"
    assert prbd_data["header_row"] == 2
    assert prbd_data["row_count"] == 4
    assert prbd_data["last_data_row"] == 6
    assert prbd_data["blank_trailing_rows"] == 2
    assert [column["qualified_name"] for column in prbd_data["columns"]] == [
        "field_b#1",
        "field_a#1",
        "field_extra#1",
    ]
    nullable_column = _column(prbd_data, "field_b#1")
    assert nullable_column["null_count"] == 3
    assert nullable_column["non_null_count"] == 1
    assert nullable_column["null_ratio"] == 0.75
    assert nullable_column["observed_nullable"] is True
    assert nullable_column["string_length_min"] is None
    assert nullable_column["string_length_max"] is None

    prbd_diff = _table(schema_diff, "PRBD01N001")
    assert prbd_diff["status"] == "MISMATCH"
    assert prbd_diff["exact_column_order_match"] is False
    assert [entry["column_name"] for entry in prbd_diff["missing_in_data"]] == [
        "field_c"
    ]
    assert [entry["column_name"] for entry in prbd_diff["missing_in_schema"]] == [
        "field_extra"
    ]
    assert {
        entry["qualified_name"] for entry in prbd_diff["order_differences"]
    } == {"field_a#1", "field_b#1"}

    duplicate_schema = _table(schema_profile, "PREF01N001")
    duplicate_data = _table(data_profile, "PREF01N001")
    duplicate_diff = _table(schema_diff, "PREF01N001")
    assert duplicate_schema["duplicate_column_names"] == [
        {
            "column_name": "field_a",
            "positions": [1, 2],
            "occurrence_count": 2,
        }
    ]
    assert duplicate_data["duplicate_column_names"] == [
        {
            "column_name": "field_a",
            "positions": [1, 2],
            "occurrence_count": 2,
        }
    ]
    assert [column["qualified_name"] for column in duplicate_data["columns"]] == [
        "field_a#1",
        "field_a#2",
        "field_b#1",
    ]
    assert duplicate_diff["status"] == "MATCH"

    formula_data = _table(data_profile, "PREF02N001")
    assert formula_data["row_count"] == 1
    assert formula_data["structure"]["formula_cell_count"] == 1
    assert formula_data["structure"]["merged_cell_count"] == 1
    assert _column(formula_data, "field_b#1")["formula_cell_count"] == 1

    date_shape_data = _table(data_profile, "PRFD01N001")
    valid_date_shape = _column(date_shape_data, "all_valid_dates#1")[
        "date_like_integer"
    ]
    mixed_integer_shape = _column(date_shape_data, "mixed_integers#1")[
        "date_like_integer"
    ]
    assert valid_date_shape == {
        "candidate": True,
        "match_count": 3,
        "integer_value_count": 3,
        "format": "YYYYMMDD",
        "interpretation": "lexical/value-shape candidate only",
    }
    assert mixed_integer_shape["candidate"] is False
    assert mixed_integer_shape["match_count"] == 1
    assert mixed_integer_shape["integer_value_count"] == 3

    # Reports describe statistics and lineage only; source row values are not
    # copied into JSON or Markdown artifacts.
    report_text = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.iterdir()
    )
    for raw_value in (
        "alpha",
        "beta",
        "gamma",
        "delta",
        "formula-row",
        "SCHEMA_SAMPLE_MUST_NOT_LEAK",
    ):
        assert raw_value not in report_text


@pytest.mark.parametrize("source_kind", ["raw", "schema"])
def test_run_rejects_output_directory_inside_read_only_source_tree(
    synthetic_workbooks,
    source_kind: str,
) -> None:
    source_dir = (
        synthetic_workbooks.raw_dir
        if source_kind == "raw"
        else synthetic_workbooks.schema_dir
    )
    output_dir = source_dir / "reports"
    before = _source_snapshot(synthetic_workbooks.all_paths)

    with pytest.raises(
        DiscoveryError,
        match="output_dir must not be inside either read-only source directory",
    ):
        run_profiling(
            synthetic_workbooks.raw_dir,
            synthetic_workbooks.schema_dir,
            output_dir,
        )

    assert not output_dir.exists()
    assert _source_snapshot(synthetic_workbooks.all_paths) == before
