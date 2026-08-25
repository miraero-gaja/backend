"""Stable G2-A artifact and contract constants."""

from __future__ import annotations

from pipeline.dataset_contract import TOTAL_COLUMNS


G2A_FORMAT_VERSION = "1.0"
EXPECTED_COVERAGE_COLUMN_COUNT = TOTAL_COLUMNS

G2A_REPORT_FILENAMES = (
    "g2a_typed_rules.json",
    "g2a_coverage_matrix.json",
    "g2a_lineage_summary.json",
    "g2a_mapping_review.json",
    "g2a_summary.md",
)


__all__ = [
    "EXPECTED_COVERAGE_COLUMN_COUNT",
    "G2A_FORMAT_VERSION",
    "G2A_REPORT_FILENAMES",
]
