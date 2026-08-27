"""Deterministic cross-product merge behavior at the executor layer.

Mirrors the FakeBackend pattern used in tests/structured/test_query_executor.py
and tests/structured/test_g3_competency.py. Each scope is executed through
the same, unmodified StructuredQueryExecutor -- these tests verify only the
merge status computed from independent per-scope outcomes, never any
row-level merge, and that TOOL_FAILURE is never conflated with UNSUPPORTED
-- matching the single-product policy where a backend/tool exception is a
ReasonCode.TOOL_FAILURE, not a semantic refusal.
"""

import asyncio

from app.evidence.models import ReasonCode, SupportStatus
from app.structured import (
    AggregateFunction,
    CrossProductMergeStatus,
    CrossProductQueryExecutor,
    CrossProductScopeStatus,
    StructuredQueryContract,
    StructuredQueryCompiler,
    StructuredQueryExecutor,
    TrustedQueryRegistry,
    TrustedTable,
    evaluate_cross_product,
)


def _compiler() -> StructuredQueryCompiler:
    return StructuredQueryCompiler(
        TrustedQueryRegistry(
            [
                TrustedTable("PREF01N001", "structured_staging", "stg_pref01n001"),
                TrustedTable("PREF02N001", "structured_staging", "stg_pref02n001"),
            ],
            [],
        )
    )


class DispatchBackend:
    """Routes each fetch by table name so independent per-scope counts can differ."""

    def __init__(self, counts_by_table: dict[str, int]) -> None:
        self._counts_by_table = counts_by_table
        self.calls: list[str] = []

    async def fetch_all(self, sql, parameters):
        self.calls.append(sql)
        for table, count in self._counts_by_table.items():
            if table in sql:
                return [{"__count": count}]
        raise AssertionError(f"unexpected table in sql: {sql}")


class FailingBackend:
    async def fetch_all(self, sql, parameters):
        raise RuntimeError("backend unavailable")


def _scopes() -> tuple[tuple[str, StructuredQueryContract], ...]:
    return (
        (
            "PREF01N001",
            StructuredQueryContract(
                product_scope="PREF01N001", aggregate=AggregateFunction.COUNT
            ),
        ),
        (
            "PREF02N001",
            StructuredQueryContract(
                product_scope="PREF02N001", aggregate=AggregateFunction.COUNT
            ),
        ),
    )


def test_two_supported_scopes_merge_all_supported() -> None:
    backend = DispatchBackend({"stg_pref01n001": 7, "stg_pref02n001": 12})
    executor = CrossProductQueryExecutor(StructuredQueryExecutor(_compiler(), backend))

    result = asyncio.run(
        executor.execute(metric=AggregateFunction.COUNT, scopes=_scopes())
    )

    assert result.status is CrossProductMergeStatus.ALL_SUPPORTED
    assert result.metric is AggregateFunction.COUNT
    outcomes_by_table = {outcome.logical_table_id: outcome for outcome in result.scopes}
    assert outcomes_by_table["PREF01N001"].status is CrossProductScopeStatus.SUPPORTED
    assert outcomes_by_table["PREF01N001"].result.candidates == ({"count": 7},)
    assert outcomes_by_table["PREF02N001"].status is CrossProductScopeStatus.SUPPORTED
    assert outcomes_by_table["PREF02N001"].result.candidates == ({"count": 12},)

    decision = evaluate_cross_product(result)
    assert decision.status is SupportStatus.SUPPORTED
    assert decision.reason_codes == ()
    assert {item.value for item in decision.aggregate_evidence} == {7, 12}
    assert {item.source_table for item in decision.aggregate_evidence} == {
        "PREF01N001",
        "PREF02N001",
    }


def test_one_scope_tool_failure_degrades_to_partial_and_preserves_the_success() -> None:
    """A single scope's backend exception must not be relabeled UNSUPPORTED
    -- it stays TOOL_FAILURE, and the merge is PARTIAL because the other
    scope did succeed. The successful scope's result must be preserved,
    never discarded because a sibling scope failed."""

    compiler = _compiler()

    class PartiallyFailingBackend:
        async def fetch_all(self, sql, parameters):
            if "stg_pref01n001" in sql:
                return [{"__count": 5}]
            raise RuntimeError("backend unavailable for this scope")

    executor = CrossProductQueryExecutor(
        StructuredQueryExecutor(compiler, PartiallyFailingBackend())
    )

    result = asyncio.run(
        executor.execute(metric=AggregateFunction.COUNT, scopes=_scopes())
    )

    assert result.status is CrossProductMergeStatus.PARTIAL
    outcomes_by_table = {outcome.logical_table_id: outcome for outcome in result.scopes}
    assert outcomes_by_table["PREF01N001"].status is CrossProductScopeStatus.SUPPORTED
    assert outcomes_by_table["PREF01N001"].result.candidates == ({"count": 5},)
    assert outcomes_by_table["PREF02N001"].status is CrossProductScopeStatus.TOOL_FAILURE
    assert outcomes_by_table["PREF02N001"].result is None
    assert outcomes_by_table["PREF02N001"].error_code is ReasonCode.TOOL_FAILURE

    decision = evaluate_cross_product(result)
    assert decision.status is SupportStatus.PARTIAL
    assert decision.reason_codes == (ReasonCode.FIELD_NOT_AVAILABLE,)
    # Only the successful scope's evidence survives into the decision.
    assert len(decision.aggregate_evidence) == 1
    assert decision.aggregate_evidence[0].source_table == "PREF01N001"
    assert decision.aggregate_evidence[0].value == 5


def test_every_scope_tool_failure_merges_tool_failure_not_unsupported() -> None:
    """When every scope fails at the backend/tool layer, the merge status
    (and the SupportDecision it maps to) must say TOOL_FAILURE, matching
    the single-product policy where a backend exception is
    ReasonCode.TOOL_FAILURE rather than a semantic UNSUPPORTED refusal."""

    executor = CrossProductQueryExecutor(
        StructuredQueryExecutor(_compiler(), FailingBackend())
    )

    result = asyncio.run(
        executor.execute(metric=AggregateFunction.COUNT, scopes=_scopes())
    )

    assert result.status is CrossProductMergeStatus.TOOL_FAILURE
    assert all(
        outcome.status is CrossProductScopeStatus.TOOL_FAILURE
        for outcome in result.scopes
    )
    assert all(
        outcome.error_code is ReasonCode.TOOL_FAILURE for outcome in result.scopes
    )

    decision = evaluate_cross_product(result)
    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.reason_codes == (ReasonCode.TOOL_FAILURE,)
    assert decision.aggregate_evidence == ()
