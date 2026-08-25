"""Physical contract for the active official 2026-08-24 dataset.

This module is the single source of truth for dataset identity and physical
shape.  It deliberately contains no column semantics, units, code meanings,
or runtime query permissions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


DATASET_VERSION = "20260824"
DATASET_SNAPSHOT_DATE = "2026-08-24"


@dataclass(frozen=True, slots=True)
class DatasetTableContract:
    """Physical identity and shape for one official logical table."""

    logical_table_id: str
    expected_rows: int
    expected_columns: int
    product_group: str
    physical_id_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.logical_table_id.strip():
            raise ValueError("logical_table_id must not be blank")
        if self.expected_rows <= 0:
            raise ValueError("expected_rows must be positive")
        if self.expected_columns <= 0:
            raise ValueError("expected_columns must be positive")
        if not self.product_group.strip():
            raise ValueError("product_group must not be blank")
        if len(set(self.physical_id_aliases)) != len(self.physical_id_aliases):
            raise ValueError("physical_id_aliases must be unique")
        if any(not alias.strip() for alias in self.physical_id_aliases):
            raise ValueError("physical_id_aliases must not contain blanks")


_TABLE_CONTRACTS = {
    "PRBD01N001": DatasetTableContract(
        logical_table_id="PRBD01N001",
        expected_rows=21_882,
        expected_columns=58,
        product_group="국내채권",
    ),
    "PREF01N001": DatasetTableContract(
        logical_table_id="PREF01N001",
        expected_rows=1_780,
        expected_columns=98,
        product_group="국내ETF",
    ),
    "PREF02N001": DatasetTableContract(
        logical_table_id="PREF02N001",
        expected_rows=6_037,
        expected_columns=49,
        product_group="해외ETF",
    ),
    "PRFD01N001": DatasetTableContract(
        logical_table_id="PRFD01N001",
        expected_rows=23_676,
        expected_columns=75,
        product_group="공모펀드",
        physical_id_aliases=("PRFDN001",),
    ),
}

TABLE_CONTRACTS: Mapping[str, DatasetTableContract] = MappingProxyType(
    _TABLE_CONTRACTS
)
OFFICIAL_TABLE_IDS = frozenset(TABLE_CONTRACTS)
TABLE_ROW_COUNTS: Mapping[str, int] = MappingProxyType(
    {
        table_id: contract.expected_rows
        for table_id, contract in TABLE_CONTRACTS.items()
    }
)
TABLE_COLUMN_COUNTS: Mapping[str, int] = MappingProxyType(
    {
        table_id: contract.expected_columns
        for table_id, contract in TABLE_CONTRACTS.items()
    }
)

TOTAL_ROWS = 53_375
TOTAL_COLUMNS = 280

if sum(TABLE_ROW_COUNTS.values()) != TOTAL_ROWS:
    raise RuntimeError("official table row counts do not match TOTAL_ROWS")
if sum(TABLE_COLUMN_COUNTS.values()) != TOTAL_COLUMNS:
    raise RuntimeError("official table column counts do not match TOTAL_COLUMNS")


def get_table_contract(logical_table_id: str) -> DatasetTableContract:
    """Return one official table contract, failing closed for unknown IDs."""

    try:
        return TABLE_CONTRACTS[logical_table_id]
    except KeyError as error:
        raise KeyError(f"unknown official logical_table_id: {logical_table_id}") from error


__all__ = [
    "DATASET_SNAPSHOT_DATE",
    "DATASET_VERSION",
    "DatasetTableContract",
    "OFFICIAL_TABLE_IDS",
    "TABLE_COLUMN_COUNTS",
    "TABLE_CONTRACTS",
    "TABLE_ROW_COUNTS",
    "TOTAL_COLUMNS",
    "TOTAL_ROWS",
    "get_table_contract",
]
