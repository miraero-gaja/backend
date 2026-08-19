"""Official G1 inputs and report contract.

Only identifiers and row counts supplied by the official task are encoded here.
No financial column meaning, unit, or datatype is inferred in this module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Official identity and expected row count for one logical table."""

    logical_table_id: str
    product_group: str
    expected_rows: int
    physical_id_aliases: tuple[str, ...] = ()


TABLE_SPECS: dict[str, TableSpec] = {
    "PRBD01N001": TableSpec("PRBD01N001", "국내채권", 42_394),
    "PREF01N001": TableSpec("PREF01N001", "국내ETF", 1_734),
    "PREF02N001": TableSpec("PREF02N001", "해외ETF", 5_646),
    "PRFD01N001": TableSpec(
        "PRFD01N001",
        "공모펀드",
        95_619,
        physical_id_aliases=("PRFDN001",),
    ),
}

EXPECTED_TOTAL_ROWS = sum(spec.expected_rows for spec in TABLE_SPECS.values())

REPORT_FILENAMES = (
    "g1_file_manifest.json",
    "g1_schema_profile.json",
    "g1_data_profile.json",
    "g1_schema_diff.json",
    "g1_summary.md",
)

PROFILE_FORMAT_VERSION = "1.0"

