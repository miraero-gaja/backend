"""Structured tool adapter with deterministic result evidence validation."""

from __future__ import annotations

from time import monotonic

from app.agent.contracts import QueryContract, ToolResult
from app.core.deadline import Deadline
from app.evidence.models import ReasonCode
from app.evidence.validator import StructuredEvidenceValidator
from app.structured import (
    StructuredExecutionResult,
    StructuredQueryContract,
    StructuredQueryExecutor,
)
from app.tools import UnavailableToolAdapter


class StructuredToolAdapter(UnavailableToolAdapter):
    """Bridge approved plans through retrieval and evidence validation."""

    tool_name = "structured"

    def __init__(
        self,
        executor: StructuredQueryExecutor | None = None,
        evidence_validator: StructuredEvidenceValidator | None = None,
    ) -> None:
        self._executor = executor
        self._evidence_validator = evidence_validator or StructuredEvidenceValidator()

    async def execute_structured(
        self,
        query: StructuredQueryContract,
        deadline: Deadline,
    ) -> StructuredExecutionResult:
        if self._executor is None:
            raise RuntimeError("structured executor is not connected")
        deadline.raise_if_expired()
        return await self._executor.execute(query)

    async def execute(self, query: QueryContract, deadline: Deadline) -> ToolResult:
        structured_query = query.structured_query
        if self._executor is None or not isinstance(
            structured_query, StructuredQueryContract
        ):
            return await super().execute(query, deadline)

        started_at = monotonic()
        result = await self.execute_structured(structured_query, deadline)
        validation_trace = self._evidence_validator.validate(
            structured_query,
            result,
        )
        if not result.candidates:
            return ToolResult(
                tool_name=self.tool_name,
                query_fingerprint=result.query_fingerprint,
                elapsed_ms=(monotonic() - started_at) * 1000,
                error_code=ReasonCode.NO_MATCH,
                validation_trace=validation_trace,
            )
        return ToolResult(
            tool_name=self.tool_name,
            query_fingerprint=result.query_fingerprint,
            candidates=result.candidates,
            columns=result.columns,
            elapsed_ms=(monotonic() - started_at) * 1000,
            evidence=result.evidence,
            aggregate_evidence=result.aggregate_evidence,
            validation_trace=validation_trace,
        )


__all__ = ["StructuredToolAdapter"]
