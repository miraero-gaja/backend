from __future__ import annotations

from itertools import cycle

import pytest

from pipeline.normalize.type_rules import build_typed_rule
from pipeline.structured.schema import (
    OFFICIAL_STAGING_COLUMN_COUNTS,
    StagingSchemaError,
    build_staging_schema,
    build_table_spec,
    render_create_schema_sql,
    render_create_table_sql,
)


def _official_rules():
    declarations = cycle(("text", "numeric", "bigint", "timestamp without time zone"))
    rules = []
    for table_id, count in OFFICIAL_STAGING_COLUMN_COUNTS.items():
        for position in range(1, count + 1):
            rules.append(
                build_typed_rule(
                    logical_table_id=table_id,
                    source_column=f"FIELD_{position}",
                    declared_type=next(declarations),
                )
            )
    return rules


def test_official_schema_materializes_four_tables_and_all_207_columns() -> None:
    schema = build_staging_schema(_official_rules())

    assert len(schema.tables) == 4
    assert schema.source_column_count == 207
    assert [len(table.columns) for table in schema.tables] == [40, 73, 49, 45]
    assert {table.db_table_name for table in schema.tables} == {
        "stg_prbd01n001",
        "stg_pref01n001",
        "stg_pref02n001",
        "stg_prfd01n001",
    }
    assert all(
        len({column.db_column_name for column in table.columns}) == len(table.columns)
        for table in schema.tables
    )
    assert schema.to_dict()["all_source_columns_materialized"] is True
    assert schema.to_dict()["agent_field_exposure_separate_from_storage"] is True


def test_occurrence_aware_physical_names_are_safe_and_deterministic() -> None:
    rules = [
        build_typed_rule(
            logical_table_id="PRBD01N001",
            source_column='PD_NO"); DROP TABLE products; --',
            occurrence=1,
            declared_type="text",
        ),
        build_typed_rule(
            logical_table_id="PRBD01N001",
            source_column='PD_NO"); DROP TABLE products; --',
            occurrence=2,
            declared_type="numeric",
        ),
    ]

    first = build_table_spec("PRBD01N001", rules)
    second = build_table_spec("PRBD01N001", rules)
    assert first == second
    assert first.columns[0].qualified_name.endswith("#1")
    assert first.columns[1].qualified_name.endswith("#2")
    assert first.columns[0].db_column_name != first.columns[1].db_column_name
    ddl = render_create_table_sql(first)
    assert ";" not in ddl
    assert "PRIMARY KEY" in ddl
    assert '"raw_record" jsonb NOT NULL' in ddl
    assert '"parse_statuses" jsonb NOT NULL' in ddl
    assert "business" not in ddl.casefold()


def test_ddl_uses_declared_postgres_types_and_technical_lineage_only() -> None:
    rules = [
        build_typed_rule(
            logical_table_id="TEST01",
            source_column="text_field",
            declared_type="text",
        ),
        build_typed_rule(
            logical_table_id="TEST01",
            source_column="decimal_field",
            declared_type="numeric",
        ),
        build_typed_rule(
            logical_table_id="TEST01",
            source_column="date_field",
            declared_type="date",
        ),
    ]
    table = build_table_spec("TEST01", rules)
    ddl = render_create_table_sql(table)

    assert render_create_schema_sql(
        build_staging_schema(rules, expected_column_counts={"TEST01": 3})
    ) == 'CREATE SCHEMA IF NOT EXISTS "structured_staging"'
    assert '"source_row_id" text PRIMARY KEY' in ddl
    assert '"source_excel_row" bigint NOT NULL' in ddl
    assert '"c001_text_field" text NULL' in ddl
    assert '"c002_decimal_field" numeric NULL' in ddl
    assert '"c003_date_field" date NULL' in ddl


def test_official_shape_rejects_missing_columns_or_unsafe_table_identity() -> None:
    rules = _official_rules()
    with pytest.raises(StagingSchemaError, match="column count mismatch"):
        build_staging_schema(rules[:-1])

    unsafe = build_typed_rule(
        logical_table_id="BAD;DROP",
        source_column="field",
        declared_type="text",
    )
    with pytest.raises(StagingSchemaError, match="invalid logical table"):
        build_staging_schema([unsafe], expected_column_counts={"BAD;DROP": 1})


def test_unsupported_declared_type_is_never_silently_materialized() -> None:
    rule = build_typed_rule(
        logical_table_id="TEST01",
        source_column="mystery",
        declared_type="money",
    )
    with pytest.raises(StagingSchemaError, match="unsupported typed target"):
        build_table_spec("TEST01", [rule])
