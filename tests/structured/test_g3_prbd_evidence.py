import json
from pathlib import Path
from typing import Any


_ARTIFACT_DIR = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "profiling"
    / "g3a1_prbd"
)
_EXPECTED_FILES = {
    "g1_data_profile.json",
    "g1_file_manifest.json",
    "g1_schema_diff.json",
    "g1_schema_profile.json",
    "g1_summary.md",
}


def _document(filename: str) -> dict[str, Any]:
    return json.loads((_ARTIFACT_DIR / filename).read_text(encoding="utf-8"))


def _prbd_column(column_name: str) -> dict[str, Any]:
    table = next(
        item
        for item in _document("g1_data_profile.json")["tables"]
        if item["logical_table_id"] == "PRBD01N001"
    )
    return next(
        item for item in table["columns"] if item["column_name"] == column_name
    )


def test_prbd_artifact_is_aggregate_only_and_hash_identified() -> None:
    assert {path.name for path in _ARTIFACT_DIR.iterdir()} == _EXPECTED_FILES

    profile = _document("g1_data_profile.json")
    assert profile["source_rows_copied"] is False
    assert profile["arbitrary_value_samples_copied"] is False

    source = next(
        item
        for item in _document("g1_file_manifest.json")["files"]
        if item["logical_table_id"] == "PRBD01N001"
        and item["source_kind"] == "datarows"
    )
    assert source["observed_rows"] == 42_394
    assert source["source_immutable"] is True
    assert source["sha256"] == (
        "728f44a567a986d21cf843d711c6c4d"
        "fa1a24d05b39c7da0541b981b57ecccf8"
    )


def test_prbd_risk_grade_records_bounded_numeric_distribution_only() -> None:
    column = _prbd_column("PD_RISK_GCD")

    assert column["row_count"] == column["non_null_count"] == 42_394
    assert column["null_count"] == 0
    assert column["distinct_count"] == 7
    assert column["observed_type_counts"] == {"integer": 42_394}
    assert column["numeric_min"] == "0"
    assert column["numeric_max"] == "6"
    assert column["non_finite_numeric_count"] == 0


def test_prbd_duration_like_columns_record_source_native_profiles_only() -> None:
    expected = {
        "DUR": (14_850, "0", "99", 8_272, 20_746),
        "NDY_DUR": (14_606, "0", "99", 8_603, 20_415),
        "COV": (16_187, "0", "2499", 8_330, 20_688),
    }

    for column_name, (
        distinct_count,
        numeric_min,
        numeric_max,
        integer_count,
        number_count,
    ) in expected.items():
        column = _prbd_column(column_name)
        assert column["row_count"] == 42_394
        assert column["non_null_count"] == 29_018
        assert column["null_count"] == column["missing_cell_count"] == 13_376
        assert column["distinct_count"] == distinct_count
        assert column["observed_type_counts"] == {
            "integer": integer_count,
            "number": number_count,
        }
        assert column["numeric_min"] == numeric_min
        assert column["numeric_max"] == numeric_max
        assert column["non_finite_numeric_count"] == 0
        assert column["empty_string_count"] == 0
        assert column["whitespace_only_count"] == 0
        assert column["excel_error_count"] == 0
        assert column["formula_cell_count"] == 0
