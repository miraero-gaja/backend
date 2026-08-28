"""Safety tests for the minimal G2 Priority A field registry."""

from __future__ import annotations

import pytest

from pipeline.dataset_contract import TABLE_COLUMN_COUNTS, TOTAL_COLUMNS
from mappings.core import (
    CORE_FIELD_MAPPINGS,
    FIELD_NULL_EQUIVALENT_POLICIES,
    NULL_EQUIVALENT,
    SOURCE_NOT_AVAILABLE,
    CoreUnitStatus,
    SemanticStatus,
    build_core_field_registry,
    get_confirmed_core_fields,
    get_confirmed_field_map,
    get_core_mapping_summary,
    validate_core_field_registry,
)


def test_priority_a_is_a_minimal_subset_with_exact_universe_counts() -> None:
    summary = get_core_mapping_summary()

    assert summary["official_column_count"] == TOTAL_COLUMNS
    assert summary["reviewed_entry_count"] == 53
    assert summary["agent_allowed_field_count"] == 49
    assert summary["semantic_status_counts"] == {
        "CONFIRMED": 49,
        "NEED_REVIEW": 4,
        "UNMAPPED": TOTAL_COLUMNS - len(CORE_FIELD_MAPPINGS),
    }
    assert summary["table_status_counts"]["PRBD01N001"] == {
        "official_column_count": TABLE_COLUMN_COUNTS["PRBD01N001"],
        "reviewed_entry_count": 4,
        "CONFIRMED": 4,
        "NEED_REVIEW": 0,
        "UNMAPPED": TABLE_COLUMN_COUNTS["PRBD01N001"] - 4,
    }
    assert summary["table_status_counts"]["PREF02N001"]["CONFIRMED"] == 4


def test_only_confirmed_fields_enter_the_immutable_agent_allowlist() -> None:
    allowlist = get_confirmed_field_map()

    assert len(allowlist) == 49
    assert all(
        mapping.semantic_status is SemanticStatus.CONFIRMED
        for mapping in allowlist.values()
    )
    assert "pref01.total_fee_rate" not in allowlist
    assert "pref01.trading_available_date" not in allowlist
    with pytest.raises(TypeError):
        allowlist["injected.field"] = next(iter(allowlist.values()))  # type: ignore[index]


def test_registry_is_occurrence_aware_table_scoped_and_structurally_valid() -> None:
    validation = validate_core_field_registry()
    registry = build_core_field_registry()

    assert validation["is_valid"] is True
    assert validation["is_minimal_subset"] is True
    assert validation["duplicate_semantic_field_keys"] == []
    assert validation["duplicate_source_identities"] == []
    assert validation["non_confirmed_with_operations"] == []
    assert validation["null_equivalent_policy_drift"] == []
    assert all(entry.qualified_name == f"{entry.source_column}#1" for entry in CORE_FIELD_MAPPINGS)
    assert registry["policy"]["agent_field_selection"] == "CONFIRMED_ONLY"
    assert registry["policy"]["semantic_keys"] == "TABLE_SCOPED_NO_CROSS_PRODUCT_MERGE"


def test_numeric_permissions_do_not_infer_missing_unit_or_scale() -> None:
    allowlist = get_confirmed_field_map()
    listed_shares = allowlist["pref01.listed_share_count"]

    assert listed_shares.target_type == "DECIMAL"
    assert listed_shares.unit_status is CoreUnitStatus.UNMAPPED
    assert listed_shares.allowed_operations == (
        "EQ",
        "NE",
        "LT",
        "LE",
        "GT",
        "GE",
        "SORT",
    )

    source_order_only = {
        "pref01.return_1m",
        "pref01.return_3m",
        "pref01.return_1y",
        "pref01.aum_latest",
        "prfd.net_assets",
        "prfd.return_1m",
        "prfd.return_3m",
        "prfd.return_1y",
    }
    assert all(
        allowlist[key].allowed_operations == ("SORT",)
        and allowlist[key].unit_status is CoreUnitStatus.UNMAPPED
        for key in source_order_only
    )


def test_text_dates_and_text_rates_are_review_only_and_have_no_operations() -> None:
    review_entries = {
        entry.semantic_field_key: entry
        for entry in CORE_FIELD_MAPPINGS
        if entry.semantic_status is SemanticStatus.NEED_REVIEW
    }

    assert set(review_entries) == {
        "pref01.total_fee_rate",
        "pref01.other_expense_rate",
        "pref01.trading_available_date",
        "pref01.trading_end_date",
    }
    assert all(entry.target_type == "TEXT" for entry in review_entries.values())
    assert all(entry.allowed_operations == () for entry in review_entries.values())


def test_table_filter_exposes_only_reviewed_fields_for_each_official_scope() -> None:
    assert len(get_confirmed_core_fields("PRBD01N001")) == 4
    assert len(get_confirmed_core_fields("PREF01N001")) == 23
    assert len(get_confirmed_core_fields("PREF02N001")) == 4
    assert len(get_confirmed_core_fields("PRFD01N001")) == 18
    with pytest.raises(KeyError, match="unknown logical_table_id"):
        get_confirmed_core_fields("INJECTED")


def test_coverage_expansion_opens_only_exact_text_equality() -> None:
    allowlist = get_confirmed_field_map()
    new_keys = {
        "prbd.product_code",
        "prbd.product_name",
        "prbd.product_mid_category_name",
        "prbd.product_sub_category_name",
        "pref01.fund_manager_name",
        "pref01.base_index_name",
        "pref01.strategy_name",
        "pref02.fund_manager_name",
        "pref02.base_index_name",
        "pref02.investment_asset_type",
        "pref02.investment_region",
        "prfd.benchmark_name",
        "prfd.class_name",
        "prfd.class_sales_channel_name",
        "prfd.zero_in_type_name",
    }

    assert new_keys <= set(allowlist)
    assert all(allowlist[key].target_type == "TEXT" for key in new_keys)
    assert all(
        allowlist[key].allowed_operations == ("EQ", "NE")
        for key in new_keys
    )
    assert all(
        allowlist[key].unit_status is CoreUnitStatus.NOT_APPLICABLE
        for key in new_keys
    )


def test_pref02_base_index_has_the_only_field_specific_null_equivalent_policy() -> None:
    allowlist = get_confirmed_field_map()
    mapping = allowlist["pref02.base_index_name"]
    policy = mapping.null_equivalent_policy

    assert set(FIELD_NULL_EQUIVALENT_POLICIES) == {
        ("PREF02N001", "pref02.base_index_name")
    }
    assert policy == FIELD_NULL_EQUIVALENT_POLICIES[
        ("PREF02N001", "pref02.base_index_name")
    ]
    assert policy is not None
    assert policy.source_classification == SOURCE_NOT_AVAILABLE
    assert policy.semantic_classification == NULL_EQUIVALENT
    assert policy.literals == (
        "Index is not provided by Management Company",
        "Index is not available on Lipper Database",
    )
    assert all(
        entry.null_equivalent_policy is None
        for entry in CORE_FIELD_MAPPINGS
        if entry.semantic_field_key != "pref02.base_index_name"
    )
    serialized = build_core_field_registry()["entries"]
    policy_entries = [
        entry for entry in serialized if "null_equivalent_policy" in entry
    ]
    assert [entry["semantic_field_key"] for entry in policy_entries] == [
        "pref02.base_index_name"
    ]
