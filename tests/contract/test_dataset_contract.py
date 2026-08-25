"""Active official dataset physical-contract tests."""

from __future__ import annotations

import pytest

from mappings.concepts import registry as concept_registry
from mappings.coverage import registry as coverage_registry
from pipeline.dataset_contract import (
    DATASET_SNAPSHOT_DATE,
    DATASET_VERSION,
    OFFICIAL_TABLE_IDS,
    TABLE_COLUMN_COUNTS,
    TABLE_CONTRACTS,
    TABLE_ROW_COUNTS,
    TOTAL_COLUMNS,
    TOTAL_ROWS,
    get_table_contract,
)
from pipeline.normalize.constants import EXPECTED_COVERAGE_COLUMN_COUNT
from pipeline.profiling.constants import EXPECTED_TOTAL_ROWS, TABLE_SPECS
from pipeline.structured.schema import (
    OFFICIAL_STAGING_COLUMN_COUNTS,
    OFFICIAL_STAGING_COLUMN_TOTAL,
)


def test_active_dataset_identity_and_physical_shape() -> None:
    assert DATASET_VERSION == "20260824"
    assert DATASET_SNAPSHOT_DATE == "2026-08-24"
    assert TABLE_ROW_COUNTS == {
        "PRBD01N001": 21_882,
        "PREF01N001": 1_780,
        "PREF02N001": 6_037,
        "PRFD01N001": 23_676,
    }
    assert TABLE_COLUMN_COUNTS == {
        "PRBD01N001": 58,
        "PREF01N001": 98,
        "PREF02N001": 49,
        "PRFD01N001": 75,
    }
    assert TOTAL_ROWS == 53_375
    assert TOTAL_COLUMNS == 280
    assert OFFICIAL_TABLE_IDS == frozenset(TABLE_CONTRACTS)


def test_table_metadata_preserves_product_groups_and_physical_alias() -> None:
    assert {
        table_id: contract.product_group
        for table_id, contract in TABLE_CONTRACTS.items()
    } == {
        "PRBD01N001": "국내채권",
        "PREF01N001": "국내ETF",
        "PREF02N001": "해외ETF",
        "PRFD01N001": "공모펀드",
    }
    assert get_table_contract("PRFD01N001").physical_id_aliases == ("PRFDN001",)
    with pytest.raises(KeyError, match="unknown official logical_table_id"):
        get_table_contract("UNKNOWN")


def test_downstream_physical_contracts_share_the_active_source_of_truth() -> None:
    assert EXPECTED_TOTAL_ROWS == TOTAL_ROWS
    assert {
        table_id: spec.expected_rows for table_id, spec in TABLE_SPECS.items()
    } == TABLE_ROW_COUNTS
    assert EXPECTED_COVERAGE_COLUMN_COUNT == TOTAL_COLUMNS
    assert OFFICIAL_STAGING_COLUMN_COUNTS is TABLE_COLUMN_COUNTS
    assert OFFICIAL_STAGING_COLUMN_TOTAL == TOTAL_COLUMNS
    assert concept_registry._OFFICIAL_TABLE_IDS is OFFICIAL_TABLE_IDS
    assert concept_registry._OFFICIAL_COLUMN_COUNT == TOTAL_COLUMNS
    assert coverage_registry.OFFICIAL_TABLE_IDS is OFFICIAL_TABLE_IDS
    assert coverage_registry.OFFICIAL_EXPECTED_COLUMN_COUNT == TOTAL_COLUMNS


def test_dataset_mappings_are_immutable() -> None:
    with pytest.raises(TypeError):
        TABLE_ROW_COUNTS["PRBD01N001"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        TABLE_COLUMN_COUNTS["PRBD01N001"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        TABLE_CONTRACTS["UNKNOWN"] = TABLE_CONTRACTS["PRBD01N001"]  # type: ignore[index]
