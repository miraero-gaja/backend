"""Parameterized SQL and trusted-identifier compiler tests."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.structured import (
    AggregateFunction,
    FilterOperator,
    StructuredFilter,
    StructuredQueryCompiler,
    StructuredQueryContract,
    StructuredQueryValidationError,
    TrustedField,
    TrustedQueryRegistry,
    TrustedTable,
    build_trusted_query_registry,
)
from mappings.core import SemanticStatus
from mappings.core.registry import CoreFieldMapping, CoreUnitStatus
from pipeline.normalize.models import TargetType
from pipeline.normalize.type_rules import build_typed_rule
from pipeline.structured import StagingSchemaSpec, build_table_spec


def _compiler() -> StructuredQueryCompiler:
    operations = frozenset({"EQ", "NE", "LT", "LE", "GT", "GE", "SORT"})
    return StructuredQueryCompiler(
        TrustedQueryRegistry(
            [
                TrustedTable(
                    logical_table_id="PRBD01N001",
                    schema_name="structured_staging",
                    table_name="stg_prbd01n001",
                )
            ],
            [
                TrustedField(
                    semantic_key="product_name",
                    logical_table_id="PRBD01N001",
                    source_column="PD_NM",
                    qualified_name="PD_NM#1",
                    physical_column="c002_pd_nm",
                    target_type=TargetType.TEXT,
                    allowed_operations=frozenset({"EQ", "NE"}),
                ),
                TrustedField(
                    semantic_key="source_native_metric",
                    logical_table_id="PRBD01N001",
                    source_column="METRIC",
                    qualified_name="METRIC#1",
                    physical_column="c012_metric",
                    target_type=TargetType.DECIMAL,
                    allowed_operations=frozenset({"SORT"}),
                ),
                TrustedField(
                    semantic_key="aum",
                    logical_table_id="PRBD01N001",
                    source_column="AUM",
                    qualified_name="AUM#1",
                    physical_column="c010_aum",
                    target_type=TargetType.DECIMAL,
                    allowed_operations=operations,
                ),
                TrustedField(
                    semantic_key="maturity_at",
                    logical_table_id="PRBD01N001",
                    source_column="MATURITY_AT",
                    qualified_name="MATURITY_AT#1",
                    physical_column="c011_maturity_at",
                    target_type=TargetType.TIMESTAMP,
                    allowed_operations=operations,
                ),
            ],
        )
    )


def test_multi_filter_sort_top_n_is_parameterized_and_stably_ordered() -> None:
    compiled = _compiler().compile(
        StructuredQueryContract(
            product_scope="PRBD01N001",
            filters=(
                StructuredFilter(
                    field="product_name", operator=FilterOperator.EQ, value="Alpha"
                ),
                StructuredFilter(field="aum", operator=FilterOperator.GE, value="10.50"),
            ),
            projections=("product_name", "aum"),
            sort={"field": "aum", "direction": "DESC"},
            limit=5,
        )
    )

    assert 'FROM "structured_staging"."stg_prbd01n001"' in compiled.sql
    assert '"c002_pd_nm" = %s' in compiled.sql
    assert '"c010_aum" >= %s' in compiled.sql
    assert (
        'ORDER BY "c010_aum" DESC NULLS LAST, "source_row_id" ASC'
        in compiled.sql
    )
    assert compiled.sql.endswith("LIMIT %s")
    assert compiled.parameters == ("Alpha", Decimal("10.50"), 5)
    assert "Alpha" not in compiled.sql
    assert "10.50" not in compiled.sql


def test_count_has_filters_but_no_projection_sort_or_limit() -> None:
    compiled = _compiler().compile(
        StructuredQueryContract(
            product_scope="PRBD01N001",
            filters=(
                StructuredFilter(field="aum", operator=FilterOperator.LT, value=100),
            ),
            aggregate=AggregateFunction.COUNT,
        )
    )

    assert compiled.sql.startswith('SELECT COUNT(*) AS "__count"')
    assert "ORDER BY" not in compiled.sql
    assert "LIMIT" not in compiled.sql
    assert compiled.parameters == (Decimal("100"),)


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (
            StructuredQueryContract(
                product_scope="PRBD01N001; DROP TABLE x",
                projections=("product_name",),
            ),
            "unknown product scope",
        ),
        (
            StructuredQueryContract(
                product_scope="PRBD01N001",
                projections=("product_name; DROP TABLE x",),
            ),
            "unknown or unconfirmed field",
        ),
        (
            StructuredQueryContract(
                product_scope="PRBD01N001",
                filters=(
                    StructuredFilter(
                        field="product_name",
                        operator=FilterOperator.GT,
                        value="x",
                    ),
                ),
                projections=("product_name",),
            ),
            "operator GT is not allowed",
        ),
        (
            StructuredQueryContract(
                product_scope="PRBD01N001",
                filters=(
                    StructuredFilter(
                        field="aum", operator=FilterOperator.GE, value="1,000"
                    ),
                ),
                projections=("product_name",),
            ),
            "malformed DECIMAL",
        ),
        (
            StructuredQueryContract(
                product_scope="PRBD01N001",
                filters=(
                    StructuredFilter(
                        field="maturity_at",
                        operator=FilterOperator.LE,
                        value="2026/08/19",
                    ),
                ),
                projections=("product_name",),
            ),
            "malformed TIMESTAMP",
        ),
    ],
)
def test_invalid_scope_field_operator_and_type_fail_before_sql(query, message) -> None:
    with pytest.raises(StructuredQueryValidationError, match=message):
        _compiler().compile(query)


def test_sql_injection_value_remains_an_opaque_bound_parameter() -> None:
    malicious = "x'; DROP TABLE structured_staging.stg_prbd01n001; --"
    compiled = _compiler().compile(
        StructuredQueryContract(
            product_scope="PRBD01N001",
            filters=(
                StructuredFilter(
                    field="product_name", operator=FilterOperator.EQ, value=malicious
                ),
            ),
            projections=("product_name",),
        )
    )

    assert malicious not in compiled.sql
    assert compiled.parameters == (malicious,)
    assert compiled.sql.count("%s") == 1


def test_timestamp_value_is_typed_before_binding() -> None:
    compiled = _compiler().compile(
        StructuredQueryContract(
            product_scope="PRBD01N001",
            filters=(
                StructuredFilter(
                    field="maturity_at",
                    operator=FilterOperator.GE,
                    value="2026-08-19 12:34:56",
                ),
            ),
            projections=("product_name",),
        )
    )

    assert compiled.parameters == (datetime(2026, 8, 19, 12, 34, 56),)


def test_confirmed_sort_only_field_can_be_projected_but_not_filtered() -> None:
    projected = _compiler().compile(
        StructuredQueryContract(
            product_scope="PRBD01N001",
            projections=("source_native_metric",),
            sort={"field": "source_native_metric", "direction": "ASC"},
        )
    )

    assert '"c012_metric" AS "__value_000"' in projected.sql
    with pytest.raises(StructuredQueryValidationError, match="operator GE is not allowed"):
        _compiler().compile(
            StructuredQueryContract(
                product_scope="PRBD01N001",
                filters=(
                    StructuredFilter(
                        field="source_native_metric", operator="GE", value=1
                    ),
                ),
                projections=("product_name",),
            )
        )


def test_registry_builder_joins_semantics_to_staging_physical_identifiers() -> None:
    rule = build_typed_rule(
        logical_table_id="PRBD01N001",
        source_column="PD_NM",
        declared_type="text",
    )
    table = build_table_spec("PRBD01N001", (rule,))
    schema = StagingSchemaSpec("structured_staging", (table,))
    mapping = CoreFieldMapping(
        semantic_field_key="prbd.product_name",
        logical_table_id="PRBD01N001",
        source_column="PD_NM",
        qualified_name="PD_NM#1",
        official_schema_description="official product name",
        target_type="TEXT",
        allowed_operations=("EQ", "NE"),
        semantic_status=SemanticStatus.CONFIRMED,
        unit_status=CoreUnitStatus.NOT_APPLICABLE,
        notes="official description",
    )

    registry = build_trusted_query_registry(schema, (mapping,))

    assert registry.table_count == 1
    assert registry.field_count == 1
    assert registry.field("PRBD01N001", "prbd.product_name").physical_column == (
        "c001_pd_nm"
    )
