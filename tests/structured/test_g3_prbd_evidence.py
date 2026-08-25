import json
from pathlib import Path
from typing import Any

from mappings.semantic.models import ClaimStatus, EvidenceTier, OperationStatus
from mappings.semantic.registry import get_semantic_field_approval


_ARTIFACT_G1_DIR = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "profiling"
    / "20260824"
    / "g1"
)
_ARTIFACT_G2A_DIR = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "profiling"
    / "20260824"
    / "g2a"
)

_PRBD_SCHEMA_SHA256 = (
    "9965126695066f9dc07951a78054e9e7"
    "639b6863d1ad2a9616f7e2d8fcadbc4f"
)
_PRBD_DATA_SHA256 = (
    "574ae5d6c1d98704712c256ed5352cba"
    "ed065ea9c3a6eb7b2a52adb305fa9001"
)

_PRBD_COLUMNS = ("pd_risk_gcd", "dur", "ndy_dur", "cov")


def _g1_document(filename: str) -> dict[str, Any]:
    return json.loads((_ARTIFACT_G1_DIR / filename).read_text(encoding="utf-8"))


def _g2a_document(filename: str) -> dict[str, Any]:
    return json.loads((_ARTIFACT_G2A_DIR / filename).read_text(encoding="utf-8"))


def _prbd_schema_table() -> dict[str, Any]:
    profile = _g1_document("g1_schema_profile.json")
    return next(
        table
        for table in profile["tables"]
        if table["logical_table_id"] == "PRBD01N001"
    )


def _prbd_schema_column(column_name: str) -> dict[str, Any]:
    table = _prbd_schema_table()
    return next(
        item
        for item in table["columns"]
        if item["column_name"] == column_name
    )


def _prbd_data_column(column_name: str) -> dict[str, Any]:
    profile = _g1_document("g1_data_profile.json")
    table = next(
        item
        for item in profile["tables"]
        if item["logical_table_id"] == "PRBD01N001"
    )
    return next(
        item
        for item in table["columns"]
        if item["column_name"] == column_name
    )


def _prbd_g2a_rule(column_name: str) -> dict[str, Any]:
    document = _g2a_document("g2a_typed_rules.json")
    return next(
        rule
        for rule in document["rules"]
        if rule["logical_table_id"] == "PRBD01N001"
        and rule["source_column"] == column_name
    )


def test_prbd_source_file_is_hash_identified_and_immutable() -> None:
    manifest = _g1_document("g1_file_manifest.json")

    datarows = next(
        item
        for item in manifest["files"]
        if item["logical_table_id"] == "PRBD01N001"
        and item["source_kind"] == "datarows"
    )
    schema = next(
        item
        for item in manifest["files"]
        if item["logical_table_id"] == "PRBD01N001"
        and item["source_kind"] == "schema"
    )

    assert datarows["observed_rows"] == 21_882
    assert datarows["source_immutable"] is True
    assert datarows["sha256"] == _PRBD_DATA_SHA256
    assert schema["source_immutable"] is True
    assert schema["sha256"] == _PRBD_SCHEMA_SHA256


def test_prbd_schema_declares_lowercase_physical_identity_and_no_pk() -> None:
    table = _prbd_schema_table()

    assert table["declared_primary_key_columns"] == []

    expected = {
        "pd_risk_gcd": ("text", "상품위험등급 원문 코드"),
        "dur": ("double precision", "듀레이션"),
        "ndy_dur": ("double precision", "익일 듀레이션"),
        "cov": ("double precision", "컨벡시티"),
    }
    for column_name, (declared_type, comment) in expected.items():
        column = _prbd_schema_column(column_name)
        assert column["column_name"] == column_name
        assert column["declared_type"] == declared_type
        assert column["display_name"] == comment
        assert column["declared_primary_key"] is False
        assert column["declared_unit"] is None


def test_prbd_risk_grade_records_bounded_code_distribution_without_meaning() -> None:
    column = _prbd_data_column("pd_risk_gcd")

    assert column["row_count"] == 21_882
    assert column["non_null_count"] == 21_882
    assert column["null_count"] == 0
    assert column["distinct_count"] == 7

    distribution = column["bounded_code_value_counts"]
    assert distribution["included"] is True
    assert distribution["complete"] is True
    assert distribution["values"] == [
        {"value": "00", "count": 19},
        {"value": "11", "count": 1441},
        {"value": "12", "count": 74},
        {"value": "13", "count": 146},
        {"value": "14", "count": 1424},
        {"value": "15", "count": 9849},
        {"value": "16", "count": 8929},
    ]
    assert "meanings are not inferred" in distribution["interpretation"]


def test_prbd_duration_like_columns_record_source_native_profiles_only() -> None:
    expected = {
        "dur": ("0", "99", 14_587),
        "ndy_dur": ("0", "99", 14_476),
        "cov": ("0", "2151.4139", 15_801),
    }

    for column_name, (numeric_min, numeric_max, distinct_count) in expected.items():
        column = _prbd_data_column(column_name)
        assert column["row_count"] == 21_882
        assert column["non_null_count"] == 21_866
        assert column["null_count"] == column["missing_cell_count"] == 16
        assert column["distinct_count"] == distinct_count
        assert column["numeric_min"] == numeric_min
        assert column["numeric_max"] == numeric_max
        assert column["non_finite_numeric_count"] == 0
        assert column["empty_string_count"] == 0
        assert column["whitespace_only_count"] == 0
        assert column["excel_error_count"] == 0
        assert column["formula_cell_count"] == 0


def test_prbd_g2a_typed_rule_parse_counts_match_registry_evidence() -> None:
    expected = {
        "pd_risk_gcd": (21_882, 21_882, 0, 0, 7),
        "dur": (21_882, 21_866, 16, 0, 14_587),
        "ndy_dur": (21_882, 21_866, 16, 0, 14_476),
        "cov": (21_882, 21_866, 16, 0, 15_801),
    }
    for column_name, (
        row_count,
        ok_count,
        missing_count,
        parse_error_count,
        distinct_count,
    ) in expected.items():
        rule = _prbd_g2a_rule(column_name)
        parse_aggregate = rule["parse_aggregate"]
        whitespace_aggregate = rule["whitespace_aggregate"]

        assert parse_aggregate["row_count"] == row_count
        assert parse_aggregate["status_counts"]["OK"] == ok_count
        assert parse_aggregate["status_counts"]["MISSING"] == missing_count
        assert parse_aggregate["status_counts"]["PARSE_ERROR"] == parse_error_count
        assert whitespace_aggregate["distinct_count_after_trim"] == distinct_count


def test_prbd_registry_concept_is_t1_confirmed_with_unit_unresolved() -> None:
    for column_name, semantic_key in (
        ("pd_risk_gcd", "prbd.pd_risk_gcd_unresolved"),
        ("dur", "prbd.dur_unresolved"),
        ("ndy_dur", "prbd.ndy_dur_unresolved"),
        ("cov", "prbd.cov_unresolved"),
    ):
        approval = get_semantic_field_approval("PRBD01N001", semantic_key)
        assert approval is not None
        assert approval.source_column == column_name
        assert approval.concept.status is ClaimStatus.CONFIRMED
        assert approval.concept.evidence_tier is EvidenceTier.T1_OFFICIAL_SCHEMA
        assert approval.unit.status is ClaimStatus.NEED_REVIEW
        assert approval.value_domain.status is ClaimStatus.NEED_REVIEW
        assert approval.open_operations == ()
        assert all(
            operation.status is OperationStatus.CLOSED
            for operation in approval.operations
        )

        concept_provenance = approval.concept.provenance[0]
        assert concept_provenance.artifact_relative_path == (
            "artifacts/profiling/20260824/g1/g1_schema_profile.json"
        )
        assert concept_provenance.source_identity == _PRBD_SCHEMA_SHA256

        value_domain_provenance = approval.value_domain.provenance[0]
        assert value_domain_provenance.artifact_relative_path == (
            "artifacts/profiling/20260824/g2a/g2a_typed_rules.json"
        )
        assert value_domain_provenance.source_identity == _PRBD_DATA_SHA256
