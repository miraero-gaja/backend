"""Occurrence-aware schema-versus-datarows comparison."""

from __future__ import annotations

from typing import Any


def compare_schema_and_data(
    schema_profile: dict[str, Any],
    data_profile: dict[str, Any],
) -> dict[str, Any]:
    """Compare exact declared and physical columns without semantic inference."""

    schema_columns = schema_profile["columns"]
    data_columns = data_profile["columns"]
    schema_by_name = {column["qualified_name"]: column for column in schema_columns}
    data_by_name = {column["qualified_name"]: column for column in data_columns}
    schema_order = [column["qualified_name"] for column in schema_columns]
    data_order = [column["qualified_name"] for column in data_columns]

    missing_in_data = [
        {
            "column_name": column["column_name"],
            "occurrence": column["occurrence"],
            "schema_position": column["position"],
        }
        for column in schema_columns
        if column["qualified_name"] not in data_by_name
    ]
    missing_in_schema = [
        {
            "column_name": column["column_name"],
            "occurrence": column["occurrence"],
            "data_position": column["position"],
        }
        for column in data_columns
        if column["qualified_name"] not in schema_by_name
    ]
    order_differences = [
        {
            "qualified_name": qualified_name,
            "column_name": schema_by_name[qualified_name]["column_name"],
            "schema_position": schema_by_name[qualified_name]["position"],
            "data_position": data_by_name[qualified_name]["position"],
        }
        for qualified_name in schema_order
        if qualified_name in data_by_name
        and schema_by_name[qualified_name]["position"]
        != data_by_name[qualified_name]["position"]
    ]
    declared_vs_observed = [
        {
            "qualified_name": qualified_name,
            "column_name": schema_by_name[qualified_name]["column_name"],
            "declared_type": schema_by_name[qualified_name]["declared_type"],
            "observed_types": data_by_name[qualified_name]["observed_types"],
            "representative_value_type": data_by_name[qualified_name][
                "representative_value_type"
            ],
            "declared_nullable": schema_by_name[qualified_name][
                "declared_nullable"
            ],
            "observed_nullable": data_by_name[qualified_name]["observed_nullable"],
            "compatibility_status": "NOT_INFERRED",
        }
        for qualified_name in schema_order
        if qualified_name in data_by_name
    ]
    exact_order_match = schema_order == data_order
    status = "MATCH" if not missing_in_data and not missing_in_schema and exact_order_match else "MISMATCH"
    return {
        "logical_table_id": schema_profile["logical_table_id"],
        "schema_physical_filename": schema_profile["physical_filename"],
        "data_physical_filename": data_profile["physical_filename"],
        "schema_column_count": len(schema_columns),
        "data_column_count": len(data_columns),
        "schema_columns": [
            {
                "position": column["position"],
                "column_name": column["column_name"],
                "occurrence": column["occurrence"],
            }
            for column in schema_columns
        ],
        "data_columns": [
            {
                "position": column["position"],
                "column_name": column["column_name"],
                "occurrence": column["occurrence"],
            }
            for column in data_columns
        ],
        "missing_in_data": missing_in_data,
        "missing_in_schema": missing_in_schema,
        "exact_column_order_match": exact_order_match,
        "order_differences": order_differences,
        "declared_vs_observed_types": declared_vs_observed,
        "status": status,
    }

