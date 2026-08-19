"""Synthetic G1-profile builders shared by G2-A tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def make_column(
    name: str,
    *,
    occurrence: int = 1,
    declared_type: str = "text",
    display_name: str | None = "Synthetic field",
    row_count: int = 4,
    non_null_count: int = 4,
    declared_primary_key: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return matching schema/data aggregate records for one source column."""

    qualified_name = f"{name}#{occurrence}"
    schema_column = {
        "column_name": name,
        "occurrence": occurrence,
        "qualified_name": qualified_name,
        "declared_type": declared_type,
        "display_name": display_name,
    }
    data_column = {
        "column_name": name,
        "occurrence": occurrence,
        "qualified_name": qualified_name,
        "declared_type": declared_type,
        "row_count": row_count,
        "non_null_count": non_null_count,
        "declared_primary_key": declared_primary_key,
    }
    return schema_column, data_column


def make_profiles(
    table_columns: dict[str, Iterable[tuple[dict[str, Any], dict[str, Any]]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build matching in-memory G1-style profiles without reading source data."""

    schema_tables: list[dict[str, Any]] = []
    data_tables: list[dict[str, Any]] = []
    for table_id, pairs_iterable in table_columns.items():
        pairs = list(pairs_iterable)
        schema_tables.append(
            {
                "logical_table_id": table_id,
                "columns": [schema for schema, _ in pairs],
            }
        )
        data_tables.append(
            {
                "logical_table_id": table_id,
                "columns": [data for _, data in pairs],
                "candidate_identifiers": [],
            }
        )
    return {"tables": schema_tables}, {"tables": data_tables}

