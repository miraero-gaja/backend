"""Synthetic metadata fixtures for G2-A contract tests.

The fixtures deliberately contain no official workbook values.  They model the
shape of the aggregate G1 reports closely enough to exercise occurrence-aware
coverage and conservative concept mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from helpers import make_column, make_profiles


OFFICIAL_SYNTHETIC_COUNTS = {
    "PRBD01N001": 40,
    "PREF01N001": 73,
    "PREF02N001": 49,
    "PRFD01N001": 45,
}


@dataclass(frozen=True, slots=True)
class SyntheticG2ASources:
    """Small complete four-table source set for read-only orchestration tests."""

    raw_dir: Path
    schema_dir: Path
    raw_paths: tuple[Path, ...]
    schema_paths: tuple[Path, ...]

    @property
    def all_paths(self) -> tuple[Path, ...]:
        return self.raw_paths + self.schema_paths


def _write_data_workbook(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "datarows"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _write_schema_workbook(
    path: Path,
    fields: list[str],
    *,
    primary_key_fields: frozenset[str] = frozenset(),
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1_Schema"
    sheet.append(["column", "key", "datatype", "description", "sample"])
    for index, field in enumerate(fields, start=1):
        sheet.append(
            [
                field,
                "PK" if field in primary_key_fields else None,
                "text",
                f"Synthetic display {index}",
                None,
            ]
        )
    workbook.save(path)
    workbook.close()


@pytest.fixture
def synthetic_g2a_sources(tmp_path: Path) -> SyntheticG2ASources:
    """Create four two-row raw workbooks and four matching schema workbooks."""

    raw_dir = tmp_path / "raw"
    schema_dir = tmp_path / "schema"
    raw_dir.mkdir()
    schema_dir.mkdir()
    definitions = {
        "PRBD01N001": (
            ["field_a", "field_b"],
            [["SYNTHETIC_ALPHA", "one"], ["SYNTHETIC_BETA", "two"]],
            frozenset(),
        ),
        "PREF01N001": (
            ["pd_exg_mkt_cd", "field_b"],
            [["", "one"], ["SYNTHETIC_MARKET", "two"]],
            frozenset({"pd_exg_mkt_cd"}),
        ),
        "PREF02N001": (
            ["field_a", "field_b"],
            [["SYNTHETIC_GAMMA", "one"], ["SYNTHETIC_DELTA", "two"]],
            frozenset(),
        ),
        "PRFD01N001": (
            ["field_a", "field_b"],
            [["SYNTHETIC_EPSILON", "one"], ["SYNTHETIC_ZETA", "two"]],
            frozenset(),
        ),
    }
    raw_paths: list[Path] = []
    schema_paths: list[Path] = []
    for table_id, (fields, rows, primary_keys) in definitions.items():
        physical_id = "PRFDN001" if table_id == "PRFD01N001" else table_id
        raw_path = raw_dir / f"{physical_id}_synthetic_datarows.xlsx"
        schema_path = schema_dir / f"{table_id}_synthetic_schema.xlsx"
        _write_data_workbook(raw_path, fields, rows)
        _write_schema_workbook(
            schema_path,
            fields,
            primary_key_fields=primary_keys,
        )
        raw_paths.append(raw_path)
        schema_paths.append(schema_path)
    return SyntheticG2ASources(
        raw_dir=raw_dir,
        schema_dir=schema_dir,
        raw_paths=tuple(raw_paths),
        schema_paths=tuple(schema_paths),
    )


@pytest.fixture
def official_synthetic_profiles() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return four synthetic tables with the official 40/73/49/45 shape.

    The first table intentionally has two occurrences of the same source name,
    proving that 207-column coverage is based on physical occurrences rather
    than a dictionary keyed only by column name.
    """

    tables: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for table_id, count in OFFICIAL_SYNTHETIC_COUNTS.items():
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for index in range(1, count + 1):
            if table_id == "PRBD01N001" and index <= 2:
                name = "duplicate_header"
                occurrence = index
            else:
                name = f"synthetic_column_{index}"
                occurrence = 1
            pairs.append(
                make_column(
                    name,
                    occurrence=occurrence,
                    display_name=f"Synthetic display {index}",
                )
            )
        tables[table_id] = pairs
    return make_profiles(tables)
