"""Structured tool adapter with an unavailable-by-default public runtime path."""

from __future__ import annotations

from time import monotonic

from app.agent.contracts import QueryContract, ToolResult
from app.core.deadline import Deadline
from app.evidence.models import ReasonCode
from app.structured import (
    StructuredExecutionResult,
    StructuredQueryContract,
    StructuredQueryExecutor,
)
from app.tools import UnavailableToolAdapter


class StructuredToolAdapter(UnavailableToolAdapter):
    """Bridge an explicitly approved structured plan into the generic tool API.

    Construction without an executor, or execution without an explicit typed
    plan, deliberately retains the public endpoint's fail-closed behavior.
    """

    tool_name = "structured"

    def __init__(
        self,
        executor: StructuredQueryExecutor | None = None,
    ) -> None:
        self._executor = executor

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
        if not result.candidates:
            return ToolResult(
                tool_name=self.tool_name,
                query_fingerprint=result.query_fingerprint,
                elapsed_ms=(monotonic() - started_at) * 1000,
                error_code=ReasonCode.NO_MATCH,
            )
        return ToolResult(
            tool_name=self.tool_name,
            query_fingerprint=result.query_fingerprint,
            candidates=result.candidates,
            columns=result.columns,
            elapsed_ms=(monotonic() - started_at) * 1000,
            evidence=result.evidence,
        )


__all__ = ["StructuredToolAdapter"]
