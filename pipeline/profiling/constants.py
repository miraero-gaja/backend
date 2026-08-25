"""Official G1 inputs and report contract.

Only identifiers and row counts supplied by the official task are encoded here.
No financial column meaning, unit, or datatype is inferred in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.dataset_contract import TABLE_CONTRACTS, TOTAL_ROWS


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Official identity and expected row count for one logical table."""

    logical_table_id: str
    product_group: str
    expected_rows: int
    physical_id_aliases: tuple[str, ...] = ()


TABLE_SPECS: dict[str, TableSpec] = {
    table_id: TableSpec(
        logical_table_id=contract.logical_table_id,
        product_group=contract.product_group,
        expected_rows=contract.expected_rows,
        physical_id_aliases=contract.physical_id_aliases,
    )
    for table_id, contract in TABLE_CONTRACTS.items()
}

EXPECTED_TOTAL_ROWS = TOTAL_ROWS

REPORT_FILENAMES = (
    "g1_file_manifest.json",
    "g1_schema_profile.json",
    "g1_data_profile.json",
    "g1_schema_diff.json",
    "g1_summary.md",
)

PROFILE_FORMAT_VERSION = "1.0"
