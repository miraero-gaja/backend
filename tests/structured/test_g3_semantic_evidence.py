import json
from pathlib import Path
from typing import Any

from mappings.semantic.models import OperationStatus
from mappings.semantic.registry import get_semantic_field_approval


_ARTIFACT_DIR = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "profiling"
    / "g3a1_pref02"
)


def _document(filename: str) -> dict[str, Any]:
    return json.loads((_ARTIFACT_DIR / filename).read_text(encoding="utf-8"))


def _pref02_column(column_name: str) -> dict[str, Any]:
    data_profile = _document("g1_data_profile.json")
    table = next(
        item
        for item in data_profile["tables"]
        if item["logical_table_id"] == "PREF02N001"
    )
    return next(
        item for item in table["columns"] if item["column_name"] == column_name
    )


def test_retained_aum_profile_supports_source_native_descending_order() -> None:
    column = _pref02_column("du_last_aum")
    numeric = column["numeric_like_string"]

    assert column["row_count"] == 5_646
    assert column["non_null_count"] == numeric["match_count"] == 5_459
    assert column["missing_cell_count"] == column["null_count"] == 187
    assert column["empty_string_count"] == 0
    assert column["whitespace_only_count"] == 0
    assert column["excel_error_count"] == 0
    assert column["formula_cell_count"] == 0
    assert numeric["candidate"] is True
    assert numeric["invalid_count"] == 0
    assert numeric["numeric_min"] == "0.00"
    assert numeric["numeric_max"] == "995484630000.00"
    assert numeric["exact_decimal_ordering_candidate"] is True
    assert numeric["nulls_require_explicit_ordering"] is True

    approval = get_semantic_field_approval("PREF02N001", "pref02.aum_latest")
    assert approval is not None
    assert approval.open_operations == ("SORT_DESC",)


def test_parseable_expense_values_do_not_open_numeric_operations() -> None:
    column = _pref02_column("cu_charge_rt")
    numeric = column["numeric_like_string"]

    assert numeric["candidate"] is True
    assert numeric["invalid_count"] == 0
    assert numeric["numeric_min"] == "0.000000"
    assert numeric["numeric_max"] == "2.500000"

    approval = get_semantic_field_approval(
        "PREF02N001", "pref02.expense_ratio"
    )
    assert approval is not None
    assert approval.open_operations == ()
    assert all(
        operation.status is OperationStatus.CLOSED
        for operation in approval.operations
    )


def test_market_code_profile_records_distribution_without_meaning() -> None:
    column = _pref02_column("pd_exg_mkt_cd")
    distribution = column["bounded_code_value_counts"]

    assert distribution["included"] is True
    assert distribution["complete"] is True
    assert distribution["values"] == [
        {"value": "101", "count": 9},
        {"value": "102", "count": 22},
        {"value": "AMX", "count": 4_241},
        {"value": "NAS", "count": 1_296},
        {"value": "NYS", "count": 78},
    ]
    assert "meanings are not inferred" in distribution["interpretation"]


def test_pref02_source_manifest_is_hash_identified_and_immutable() -> None:
    manifest = _document("g1_file_manifest.json")
    source = next(
        item
        for item in manifest["files"]
        if item["logical_table_id"] == "PREF02N001"
        and item["source_kind"] == "datarows"
    )

    assert source["observed_rows"] == 5_646
    assert source["source_immutable"] is True
    assert source["sha256"] == (
        "3cec19043f742771e0016d56fe806f19"
        "ad78f4295d1ae59192740a78feb2253b"
    )
