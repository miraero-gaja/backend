"""G3-A2 competency QA for semantic-gated structured execution."""

import asyncio
from decimal import Decimal

import pytest

from app.structured import (
    FilterOperator,
    SemanticGatedQueryPlanner,
    SemanticQueryUnsupportedError,
    StructuredFilter,
    StructuredQueryContract,
    StructuredQueryExecutor,
    StructuredQueryStatus,
)
from pipeline.normalize.type_rules import build_typed_rule
from pipeline.structured import build_staging_schema


def _planner() -> SemanticGatedQueryPlanner:
    rules = (
        build_typed_rule(
            logical_table_id="PREF02N001",
            source_column="du_last_aum",
            declared_type="numeric",
        ),
        build_typed_rule(
            logical_table_id="PREF02N001",
            source_column="cu_charge_rt",
            declared_type="numeric",
        ),
        build_typed_rule(
            logical_table_id="PRBD01N001",
            source_column="pd_risk_gcd",
            declared_type="text",
        ),
        build_typed_rule(
            logical_table_id="PRBD01N001",
            source_column="dur",
            declared_type="double precision",
        ),
        build_typed_rule(
            logical_table_id="PRBD01N001",
            source_column="ndy_dur",
            declared_type="double precision",
        ),
        build_typed_rule(
            logical_table_id="PRBD01N001",
            source_column="cov",
            declared_type="double precision",
        ),
    )
    schema = build_staging_schema(
        rules,
        expected_column_counts={"PREF02N001": 2, "PRBD01N001": 4},
    )
    return SemanticGatedQueryPlanner(schema)


class FakeBackend:
    def __init__(self, rows=()):
        self.rows = tuple(rows)
        self.calls = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return self.rows


def _aum_top_n(limit: int = 3) -> StructuredQueryContract:
    return StructuredQueryContract(
        product_scope="PREF02N001",
        projections=("pref02.aum_latest",),
        sort={"field": "pref02.aum_latest", "direction": "DESC"},
        limit=limit,
    )


def _assert_runtime_unsupported(
    query: StructuredQueryContract,
) -> SemanticQueryUnsupportedError:
    backend = FakeBackend()
    with pytest.raises(SemanticQueryUnsupportedError) as captured:
        asyncio.run(StructuredQueryExecutor(_planner(), backend).execute(query))

    error = captured.value
    assert error.status is StructuredQueryStatus.UNSUPPORTED
    assert error.semantic_gate_trace[-1].status is StructuredQueryStatus.UNSUPPORTED
    assert backend.calls == []
    return error


def test_pref02_aum_desc_top_n_is_supported_and_traceable() -> None:
    rows = tuple(
        {
            "__source_row_id": f"srid:v1:{index}",
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
    result = asyncio.run(
        StructuredQueryExecutor(_planner(), backend).execute(_aum_top_n())
    )

    assert result.status is StructuredQueryStatus.SUPPORTED
    assert result.candidates == (
        {"pref02.aum_latest": "30"},
        {"pref02.aum_latest": "20"},
        {"pref02.aum_latest": "10"},
    )
    assert len(backend.calls) == 1
    sql, parameters = backend.calls[0]
    assert 'ORDER BY "c001_du_last_aum" DESC NULLS LAST' in sql
    assert parameters == (3,)
    assert tuple(item.summary for item in result.semantic_gate_trace) == (
        "product_scope_selected",
        "concept_confirmed",
        "operation_open",
        "operation_open",
        "top_3_ready",
    )


def test_pref02_aum_absolute_threshold_is_unsupported() -> None:
    error = _assert_runtime_unsupported(
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
        )
    )

    assert error.semantic_gate_trace[-1].operation == "GE"
    assert error.semantic_gate_trace[-1].summary == "operation_not_open"


def test_pref02_expense_ratio_threshold_is_unsupported() -> None:
    error = _assert_runtime_unsupported(
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
        )
    )

    assert error.semantic_gate_trace[-1].operation == "LE"
    assert error.semantic_gate_trace[-1].summary == "operation_not_open"


def test_prbd_risk_code_semantic_query_is_unsupported() -> None:
    """The PRBD risk-grade concept is now T1-confirmed from the official
    schema, but its EQ operation stays CLOSED until code-value meaning is
    approved, so the query is blocked at the operation gate rather than the
    concept gate.
    """

    error = _assert_runtime_unsupported(
        StructuredQueryContract(
            product_scope="PRBD01N001",
            filters=(
                StructuredFilter(
                    field="prbd.pd_risk_gcd_unresolved",
                    operator=FilterOperator.EQ,
                    value=1,
                ),
            ),
            projections=("prbd.pd_risk_gcd_unresolved",),
        )
    )

    assert error.semantic_gate_trace[-1].operation == "EQ"
    assert error.semantic_gate_trace[-1].summary == "operation_not_open"


@pytest.mark.parametrize(
    "semantic_key",
    (
        "prbd.dur_unresolved",
        "prbd.ndy_dur_unresolved",
        "prbd.cov_unresolved",
    ),
)
def test_prbd_duration_semantic_queries_are_unsupported(
    semantic_key: str,
) -> None:
    """PRBD duration-like concepts are T1-confirmed, but SORT_DESC stays
    CLOSED until unit/scale is approved, so the query is blocked at the
    operation gate rather than the concept gate.
    """

    error = _assert_runtime_unsupported(
        StructuredQueryContract(
            product_scope="PRBD01N001",
            projections=(semantic_key,),
            sort={"field": semantic_key, "direction": "DESC"},
            limit=3,
        )
    )

    assert error.semantic_gate_trace[-1].operation == "SORT_DESC"
    assert error.semantic_gate_trace[-1].summary == "operation_not_open"


def test_supported_query_with_zero_rows_is_no_match_not_unsupported() -> None:
    backend = FakeBackend()
    result = asyncio.run(
        StructuredQueryExecutor(_planner(), backend).execute(_aum_top_n())
    )

    assert result.status is StructuredQueryStatus.NO_MATCH
    assert result.candidates == ()
    assert len(backend.calls) == 1
    assert all(
        item.status is StructuredQueryStatus.SUPPORTED
        for item in result.semantic_gate_trace
    )


def test_unknown_semantic_key_fails_closed_before_execution() -> None:
    error = _assert_runtime_unsupported(
        StructuredQueryContract(
            product_scope="PREF02N001",
            projections=("pref02.not_registered",),
        )
    )

    assert error.semantic_gate_trace[-1].summary == "unknown_semantic_key"


def test_no_query_is_marked_resolved_with_assumption_implicitly() -> None:
    compiled = _planner().compile(_aum_top_n())

    assert compiled.planning_status is StructuredQueryStatus.SUPPORTED
    assert all(
        item.status is not StructuredQueryStatus.RESOLVED_WITH_ASSUMPTION
        for item in compiled.semantic_gate_trace
    )
