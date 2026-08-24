"""Production composition checks for the G2-preserving G3 runtime gate."""

import asyncio
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.main import create_app
from app.structured import (
    FilterOperator,
    LayeredStructuredQueryPlanner,
    SemanticGatedQueryPlanner,
    SemanticQueryUnsupportedError,
    StructuredFilter,
    StructuredQueryContract,
    StructuredQueryStatus,
    StructuredQueryValidationError,
)
from pipeline.structured import OFFICIAL_STAGING_COLUMN_TOTAL


class FakeBackend:
    def __init__(self, rows=()):
        self.rows = tuple(rows)
        self.calls = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return self.rows


def _application(backend: FakeBackend):
    return create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    )


def _aum_top_n() -> StructuredQueryContract:
    return StructuredQueryContract(
        product_scope="PREF02N001",
        projections=("pref02.aum_latest",),
        sort={"field": "pref02.aum_latest", "direction": "DESC"},
        limit=3,
    )


def test_application_created_executor_uses_full_schema_and_semantic_planner() -> None:
    runtime = _application(FakeBackend()).state.runtime

    assert runtime.staging_schema.source_column_count == (
        OFFICIAL_STAGING_COLUMN_TOTAL
    )
    assert len(runtime.staging_schema.tables) == 4
    assert runtime.g2_registry.table_count == 4
    assert runtime.g2_registry.field_count == 34
    assert isinstance(runtime.semantic_planner, SemanticGatedQueryPlanner)
    assert isinstance(runtime.structured_planner, LayeredStructuredQueryPlanner)
    assert runtime.structured_executor.planner is runtime.structured_planner
    assert (
        runtime.structured_planner.semantic_planner
        is runtime.semantic_planner
    )


def test_application_wired_pref02_aum_desc_top_n_is_supported() -> None:
    rows = tuple(
        {
            "__source_row_id": f"srid:v1:wiring-{index}",
            "__logical_table_id": "PREF02N001",
            "__raw_record": {
                "du_last_aum#1": {"type": "DECIMAL", "value": value}
            },
            "__parse_statuses": {"du_last_aum#1": "OK"},
            "__value_000": Decimal(value),
        }
        for index, value in enumerate(("30", "20", "10"), start=1)
    )
    backend = FakeBackend(rows)
    runtime = _application(backend).state.runtime

    result = asyncio.run(runtime.structured_executor.execute(_aum_top_n()))

    assert result.status is StructuredQueryStatus.SUPPORTED
    assert len(backend.calls) == 1
    sql, parameters = backend.calls[0]
    assert 'ORDER BY "c019_du_last_aum" DESC NULLS LAST' in sql
    assert parameters == (3,)
    assert tuple(item.summary for item in result.semantic_gate_trace) == (
        "product_scope_selected",
        "concept_confirmed",
        "operation_open",
        "operation_open",
        "top_3_ready",
    )


@pytest.mark.parametrize(
    "query",
    (
        StructuredQueryContract(
            product_scope="PREF02N001",
            filters=(
                StructuredFilter(
                    field="pref02.aum_latest",
                    operator=FilterOperator.GE,
                    value="100",
                ),
            ),
            projections=("pref02.aum_latest",),
        ),
        StructuredQueryContract(
            product_scope="PREF02N001",
            filters=(
                StructuredFilter(
                    field="pref02.expense_ratio",
                    operator=FilterOperator.LE,
                    value="0.5",
                ),
            ),
            projections=("pref02.expense_ratio",),
        ),
    ),
)
def test_application_wired_closed_operations_stop_before_backend(
    query: StructuredQueryContract,
) -> None:
    backend = FakeBackend()
    runtime = _application(backend).state.runtime

    with pytest.raises(SemanticQueryUnsupportedError) as captured:
        asyncio.run(runtime.structured_executor.execute(query))

    assert captured.value.status is StructuredQueryStatus.UNSUPPORTED
    assert captured.value.semantic_gate_trace[-1].summary == (
        "operation_not_open"
    )
    assert backend.calls == []


def test_application_wired_unknown_semantic_key_fails_closed() -> None:
    backend = FakeBackend()
    runtime = _application(backend).state.runtime
    query = StructuredQueryContract(
        product_scope="PREF02N001",
        projections=("pref02.not_registered",),
    )

    with pytest.raises(
        StructuredQueryValidationError,
        match="unknown or unconfirmed field",
    ):
        asyncio.run(runtime.structured_executor.execute(query))

    assert backend.calls == []


def test_application_layered_planner_preserves_existing_g2_path() -> None:
    runtime = _application(FakeBackend()).state.runtime
    query = StructuredQueryContract(
        product_scope="PREF01N001",
        filters=(
            StructuredFilter(
                field="pref01.product_code",
                operator=FilterOperator.EQ,
                value="TEST-CODE",
            ),
        ),
        projections=("pref01.product_name",),
    )

    compiled = runtime.structured_planner.compile(query)

    assert 'FROM "structured_staging"."stg_pref01n001"' in compiled.sql
    assert compiled.parameters == ("TEST-CODE",)
    assert compiled.semantic_gate_trace == ()
