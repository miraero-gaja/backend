"""Deterministic executor for cross-product structured queries.

Each product scope is executed independently through the existing,
unmodified ``StructuredQueryExecutor`` -- one call per scope, exactly the
same code path a single-product query already uses. Results are merged
only at the outcome-status level (never at the row level, and never by
HCX): a metric is only ever attempted here if
``app.agent.cross_product_compat.is_cross_product_metric_compatible``
approved it during grounding, so this module does not re-decide
comparability -- it only decides the merge *status* from what each scope's
independent execution actually returned.

Status policy (kept identical to the single-product policy in
``app.evidence.validator.EvidenceValidator``):
- A raised exception from execution (a DB/backend/compiler failure) is a
  TOOL_FAILURE, exactly like ``app.agent.executor.ToolExecutor`` converts
  an adapter exception into ``ReasonCode.TOOL_FAILURE`` rather than
  ``UNSUPPORTED``. It is never silently coerced into
  ``StructuredQueryStatus.UNSUPPORTED``, which means something different
  (a semantic/grounding refusal, not an infrastructure failure).
- A scope that itself executed and returned a status (SUPPORTED, NO_MATCH,
  UNSUPPORTED, RESOLVED_WITH_ASSUMPTION) keeps that exact status.
- The merge is ALL_SUPPORTED only when every scope is SUPPORTED, PARTIAL
  when at least one scope is SUPPORTED and at least one is not (whatever
  the other scope's failure mode), TOOL_FAILURE when there is no supported
  scope and at least one scope failed at the tool/execution layer, and
  UNSUPPORTED only when no scope failed at the tool layer either (i.e.
  every scope's own execution said UNSUPPORTED/NO_MATCH).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.evidence.models import ReasonCode, SupportDecision, SupportStatus
from app.structured.contracts import (
    AggregateFunction,
    StructuredQueryContract,
    StructuredQueryStatus,
)
from app.structured.executor import StructuredExecutionResult, StructuredQueryExecutor


class CrossProductMergeStatus(StrEnum):
    """Deterministic merge outcome across independently retrieved scopes."""

    ALL_SUPPORTED = "ALL_SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    TOOL_FAILURE = "TOOL_FAILURE"


class CrossProductScopeStatus(StrEnum):
    """One scope's own outcome -- a superset of ``StructuredQueryStatus``
    that additionally distinguishes an execution-layer TOOL_FAILURE from a
    semantic/grounding UNSUPPORTED. The two must never be conflated: a
    TOOL_FAILURE says the backend could not be reached or errored, while
    UNSUPPORTED says the (already-approved) plan itself was refused."""

    SUPPORTED = "SUPPORTED"
    NO_MATCH = "NO_MATCH"
    UNSUPPORTED = "UNSUPPORTED"
    RESOLVED_WITH_ASSUMPTION = "RESOLVED_WITH_ASSUMPTION"
    TOOL_FAILURE = "TOOL_FAILURE"

    @classmethod
    def from_structured_status(cls, status: StructuredQueryStatus) -> "CrossProductScopeStatus":
        return cls(status.value)


@dataclass(frozen=True)
class CrossProductScopeOutcome:
    """The independent retrieval outcome for exactly one product scope."""

    logical_table_id: str
    status: CrossProductScopeStatus
    result: StructuredExecutionResult | None
    error_code: ReasonCode | None = None


@dataclass(frozen=True)
class CrossProductExecutionResult:
    """The deterministic merge of every scope's independent outcome."""

    metric: AggregateFunction
    status: CrossProductMergeStatus
    scopes: tuple[CrossProductScopeOutcome, ...]


class CrossProductQueryExecutor:
    """Runs one ``StructuredQueryContract`` per product scope and merges
    the outcomes deterministically -- never row-level, never inferred."""

    def __init__(self, executor: StructuredQueryExecutor) -> None:
        self._executor = executor

    async def execute(
        self,
        *,
        metric: AggregateFunction,
        scopes: tuple[tuple[str, StructuredQueryContract], ...],
    ) -> CrossProductExecutionResult:
        outcomes: list[CrossProductScopeOutcome] = []
        for logical_table_id, contract in scopes:
            try:
                result = await self._executor.execute(contract)
            except Exception:  # noqa: BLE001 - a backend/compiler failure, not a semantic refusal
                outcomes.append(
                    CrossProductScopeOutcome(
                        logical_table_id=logical_table_id,
                        status=CrossProductScopeStatus.TOOL_FAILURE,
                        result=None,
                        error_code=ReasonCode.TOOL_FAILURE,
                    )
                )
                continue
            outcomes.append(
                CrossProductScopeOutcome(
                    logical_table_id=logical_table_id,
                    status=CrossProductScopeStatus.from_structured_status(result.status),
                    result=result,
                    error_code=None,
                )
            )

        supported = [
            outcome
            for outcome in outcomes
            if outcome.status is CrossProductScopeStatus.SUPPORTED
        ]
        tool_failed = [
            outcome
            for outcome in outcomes
            if outcome.status is CrossProductScopeStatus.TOOL_FAILURE
        ]

        if outcomes and len(supported) == len(outcomes):
            merge_status = CrossProductMergeStatus.ALL_SUPPORTED
        elif supported:
            merge_status = CrossProductMergeStatus.PARTIAL
        elif tool_failed:
            merge_status = CrossProductMergeStatus.TOOL_FAILURE
        else:
            merge_status = CrossProductMergeStatus.UNSUPPORTED

        return CrossProductExecutionResult(
            metric=metric,
            status=merge_status,
            scopes=tuple(outcomes),
        )


def evaluate_cross_product(result: CrossProductExecutionResult) -> SupportDecision:
    """Map a cross-product merge outcome to the same SupportStatus/ReasonCode
    the single-product ``EvidenceValidator`` uses, so cross-product answers
    are never held to a looser or different fail-closed policy:

    - ALL_SUPPORTED -> SUPPORTED, carrying only confirmed scopes' evidence.
    - PARTIAL -> PARTIAL; the confirmed scope(s)' evidence is preserved,
      the failed/refused scope(s) contribute nothing (never fabricated).
    - TOOL_FAILURE (no scope supported, at least one backend/tool failure)
      -> UNSUPPORTED with ``ReasonCode.TOOL_FAILURE``, matching how
      ``ToolExecutor``/``EvidenceValidator`` report a single-product tool
      failure.
    - UNSUPPORTED (no scope supported, no tool failure either) ->
      UNSUPPORTED with ``ReasonCode.FIELD_NOT_AVAILABLE``, matching the
      single-product semantic-refusal case.
    """

    aggregate_evidence = tuple(
        item
        for outcome in result.scopes
        if outcome.status is CrossProductScopeStatus.SUPPORTED and outcome.result is not None
        for item in outcome.result.aggregate_evidence
    )
    if result.status is CrossProductMergeStatus.ALL_SUPPORTED:
        return SupportDecision(
            status=SupportStatus.SUPPORTED,
            aggregate_evidence=aggregate_evidence,
            summary="cross-product COUNT 전체 상품군 확정 → SUPPORTED",
        )
    if result.status is CrossProductMergeStatus.PARTIAL:
        return SupportDecision(
            status=SupportStatus.PARTIAL,
            reason_codes=(ReasonCode.FIELD_NOT_AVAILABLE,),
            aggregate_evidence=aggregate_evidence,
            summary="cross-product 일부 상품군만 확정 → PARTIAL",
        )
    if result.status is CrossProductMergeStatus.TOOL_FAILURE:
        return SupportDecision(
            status=SupportStatus.UNSUPPORTED,
            reason_codes=(ReasonCode.TOOL_FAILURE,),
            summary="cross-product 조회 실패 → TOOL_FAILURE",
        )
    return SupportDecision(
        status=SupportStatus.UNSUPPORTED,
        reason_codes=(ReasonCode.FIELD_NOT_AVAILABLE,),
        summary="cross-product 결과 승인 실패 → UNSUPPORTED",
    )
