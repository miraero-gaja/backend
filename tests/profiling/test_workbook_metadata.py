"""Synthetic structural tests for read-only XLSX metadata inspection."""

from __future__ import annotations

import hashlib

from pipeline.profiling.workbook_metadata import inspect_workbook_metadata


def _snapshot(path) -> tuple[bytes, str, int]:
    content = path.read_bytes()
    return content, hashlib.sha256(content).hexdigest(), path.stat().st_mtime_ns


def test_metadata_distinguishes_data_rows_from_styled_trailing_blanks(
    synthetic_workbooks,
) -> None:
    source_path = synthetic_workbooks.write_data(
        "PRBD01N001",
        headers=["field_a", "field_b"],
        rows=[["alpha", 1], ["beta", 2]],
        trailing_blank_rows=3,
    )

    sheet = inspect_workbook_metadata(source_path).sheet("datarows")

    assert sheet.xml_row_element_count == 6
    assert sheet.xml_last_row == 6
    assert sheet.xml_last_nonempty_row == 3
    assert sheet.blank_trailing_rows == 3
    assert sheet.dimension_max_row == 6
    assert sheet.dimension_max_column == 2


def test_metadata_reports_formula_and_merge_without_evaluating_them(
    synthetic_workbooks,
) -> None:
    source_path = synthetic_workbooks.write_data(
        "PREF01N001",
        headers=["field_a", "field_b"],
        rows=[["alpha", "=1+1"]],
        merged_ranges=("A4:B4",),
    )

    sheet = inspect_workbook_metadata(source_path).sheet("datarows")

    assert sheet.formula_cell_count == 1
    assert sheet.merged_cell_count == 1


def test_metadata_inspection_does_not_change_source_bytes_hash_or_mtime(
    synthetic_workbooks,
) -> None:
    source_path = synthetic_workbooks.raw_paths["PREF02N001"]
    before = _snapshot(source_path)

    metadata = inspect_workbook_metadata(source_path)

    assert metadata.sheet_names == ["datarows"]
    assert _snapshot(source_path) == before

