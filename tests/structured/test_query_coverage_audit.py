"""Contract checks for the complete 280-column coverage audit."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_query_coverage_audit import build_report


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "outputs/reports/query_coverage_audit_20260824.json"


def _by_source(report):
    return {
        (entry["logical_table"], entry["source_column"]): entry
        for entry in report["entries"]
    }


def test_audit_is_reproducible_complete_and_occurrence_aware() -> None:
    tracked = json.loads(REPORT.read_text(encoding="utf-8"))
    rebuilt = build_report()

    assert tracked == rebuilt
    assert tracked["official_column_count"] == 280
    assert len(tracked["entries"]) == 280
    assert len({
        (entry["logical_table"], entry["qualified_name"])
        for entry in tracked["entries"]
    }) == 280
    assert set(tracked["decision_counts"]) == {
        "SAFE_TO_OPEN",
        "REVIEW_REQUIRED",
        "KEEP_CLOSED",
    }
    assert sum(tracked["decision_counts"].values()) == 280
    assert tracked["baseline_effective_approved_field_count"] == 37
    assert tracked["implemented_effective_approved_field_count"] == 52
    assert tracked["new_effective_approved_field_count"] == 15
    assert tracked["policy"]["archive_20260711_used_as_current_evidence"] is False


def test_only_reviewed_text_operations_were_added() -> None:
    report = build_report()
    changed = [
        entry for entry in report["entries"]
        if entry["additional_operations"]
    ]

    assert len(changed) == 17  # 15 new fields plus two PREF02 op upgrades.
    assert all(entry["decision"] == "SAFE_TO_OPEN" for entry in changed)
    assert all(entry["target_type"] == "TEXT" for entry in changed)
    assert all(
        set(entry["additional_operations"]) <= {"PROJECT", "EQ", "NE"}
        for entry in changed
    )
    assert all(
        not ({"LT", "LE", "GT", "GE", "SORT", "SORT_ASC", "SORT_DESC"}
             & set(entry["additional_operations"]))
        for entry in changed
    )


def test_unitless_numeric_code_ordering_and_date_sentinels_remain_closed() -> None:
    entries = _by_source(build_report())

    for identity in (
        ("PREF02N001", "cu_charge_rt"),
        ("PRBD01N001", "dur"),
        ("PRBD01N001", "ndy_dur"),
        ("PRBD01N001", "cov"),
        ("PRBD01N001", "pd_risk_gcd"),
        ("PREF02N001", "pd_exg_mkt_cd"),
    ):
        entry = entries[identity]
        assert entry["additional_operations"] == []
        assert entry["potential_operations_after_review"] == []

    for identity in (
        ("PRBD01N001", "crd_grd_dt"),
        ("PRBD01N001", "isu_dt"),
        ("PRBD01N001", "mat_dt"),
        ("PREF02N001", "pd_lstg_dt"),
    ):
        entry = entries[identity]
        assert entry["decision"] == "REVIEW_REQUIRED"
        assert entry["implemented_operations"] == []
        assert not ({"LT", "LE", "GT", "GE", "SORT"}
                    & set(entry["potential_operations_after_review"]))


def test_info_seq_is_integer_sequence_not_date_like() -> None:
    entry = _by_source(build_report())[("PRBD01N001", "info_seq")]

    assert entry["official_schema_label_comment"] == (
        "동일 종목/시장/기준일 내 판매 LOT 구분 순번"
    )
    assert entry["physical_type"] == "bigint"
    assert entry["target_type"] == "INTEGER"
    assert entry["domain_evidence"]["date_like_string_candidate"] is False
    assert entry["decision"] == "KEEP_CLOSED"
    assert entry["current_operations"] == []
    assert entry["additional_operations"] == []
    assert entry["implemented_operations"] == []
    assert entry["potential_operations_after_review"] == []
    assert "date-like" not in entry["reason"]
    assert "physical target remains TEXT" not in entry["reason"]


def test_null_and_whitespace_policies_are_never_reinterpreted() -> None:
    for entry in build_report()["entries"]:
        domain = entry["domain_evidence"]
        assert domain["null_policy"] == "PRESERVE_MISSING"
        assert domain["whitespace_policy"] == "PRESERVE"


def test_pref02_base_index_audit_records_the_field_specific_sentinel_policy() -> None:
    entry = _by_source(build_report())[("PREF02N001", "cu_base_index")]

    assert entry["implemented_operations"] == ["PROJECT", "EQ", "NE"]
    assert "SOURCE_NOT_AVAILABLE" in entry["reason"]
    assert "NULL_EQUIVALENT" in entry["reason"]
    assert "without rewriting raw/staging values" in entry["reason"]
