"""Occurrence-aware coverage and conservative concept mapping tests."""

from __future__ import annotations

from typing import Any

from mappings.concepts import build_concept_registry
from mappings.coverage import build_coverage_registry

from helpers import make_column, make_profiles


def test_coverage_registry_has_exact_207_occurrence_aware_entries_and_100_percent(
    official_synthetic_profiles: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    schema_profile, data_profile = official_synthetic_profiles

    registry = build_coverage_registry(schema_profile, data_profile)

    assert registry["summary"]["actual_column_count"] == 207
    assert registry["summary"]["registry_entry_count"] == 207
    assert registry["summary"]["covered_column_count"] == 207
    assert registry["summary"]["coverage_ratio"] == 1.0
    assert registry["validation"]["exact_source_coverage"] is True
    assert registry["validation"]["expected_column_count_match"] is True
    assert registry["validation"]["is_valid"] is True
    identities = {
        (entry["logical_table_id"], entry["qualified_name"])
        for entry in registry["entries"]
    }
    assert len(identities) == 207
    assert ("PRBD01N001", "duplicate_header#1") in identities
    assert ("PRBD01N001", "duplicate_header#2") in identities


def test_concepts_are_never_confirmed_without_canonical_vocabulary() -> None:
    pairs = [
        make_column("with_display", display_name="Official synthetic label"),
        make_column("without_display", display_name=None),
        make_column("blank_display", display_name="   "),
    ]
    schema_profile, _ = make_profiles({"SYNTHETIC": pairs})

    registry = build_concept_registry(schema_profile)
    entries = {entry["source_column"]: entry for entry in registry["entries"]}

    assert registry["summary"]["status_counts"] == {
        "CONFIRMED": 0,
        "CANDIDATE": 1,
        "UNMAPPED": 2,
    }
    assert registry["validation"]["confirmed_without_canonical_vocabulary"] == []
    assert entries["with_display"]["concept_candidate"] == "Official synthetic label"
    assert entries["with_display"]["concept_status"] == "CANDIDATE"
    assert entries["without_display"]["concept_candidate"] is None
    assert entries["without_display"]["concept_status"] == "UNMAPPED"
    assert entries["blank_display"]["concept_status"] == "UNMAPPED"
    assert all(entry["concept_status"] != "CONFIRMED" for entry in registry["entries"])


def test_same_display_label_is_not_semantically_merged_across_tables() -> None:
    schema_profile, _ = make_profiles(
        {
            "TABLE_A": [make_column("field_a", display_name="Shared label")],
            "TABLE_B": [make_column("field_b", display_name="Shared label")],
        }
    )

    registry = build_concept_registry(schema_profile)

    assert len(registry["entries"]) == 2
    assert registry["policy"]["semantic_unification_performed"] is False
    assert {entry["logical_table_id"] for entry in registry["entries"]} == {
        "TABLE_A",
        "TABLE_B",
    }


def test_pref01_declared_key_with_one_blank_is_not_a_business_primary_key() -> None:
    pairs = [
        make_column(
            "pd_exg_mkt_cd",
            display_name="Synthetic market code",
            row_count=2,
            non_null_count=1,
            declared_primary_key=True,
        ),
        make_column(
            "pd_itm_no",
            display_name="Synthetic item code",
            row_count=2,
            non_null_count=2,
            declared_primary_key=True,
        ),
        make_column(
            "pd_itm_no_ma",
            display_name="Synthetic item code suffix",
            row_count=2,
            non_null_count=2,
            declared_primary_key=True,
        ),
    ]
    schema_profile, data_profile = make_profiles({"PREF01N001": pairs})

    registry = build_coverage_registry(
        schema_profile,
        data_profile,
        expected_column_count=3,
    )
    entries = {entry["source_column"]: entry for entry in registry["entries"]}
    blank_component = entries["pd_exg_mkt_cd"]

    assert blank_component["identifier_role"] == "DECLARED_KEY_COMPONENT"
    assert blank_component["non_null_ratio"] == 0.5
    assert "business primary key" in blank_component["notes"]
    assert blank_component["supported_operations"] == []
    assert all(entry["identifier_role"] != "BUSINESS_PRIMARY_KEY" for entry in registry["entries"])
