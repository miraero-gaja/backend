"""Retrieval adapter contracts with unavailable-by-default implementations."""

import hashlib
import json
from typing import Protocol

from app.agent.contracts import QueryContract, ToolResult
from app.core.deadline import Deadline
from app.evidence.models import ReasonCode


class ToolAdapter(Protocol):
    tool_name: str

    async def execute(self, query: QueryContract, deadline: Deadline) -> ToolResult: ...


def query_fingerprint(query: QueryContract) -> str:
    """Hash a plan without request identifiers or raw user question text."""

    plan = query.model_dump(mode="json", exclude={"request_id", "question_id"})
    encoded = json.dumps(
        plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class UnavailableToolAdapter:
    """Safe adapter base that never fabricates candidates."""

    tool_name = "unavailable"

    async def execute(self, query: QueryContract, deadline: Deadline) -> ToolResult:
        deadline.raise_if_expired()
        return ToolResult(
            tool_name=self.tool_name,
            query_fingerprint=query_fingerprint(query),
            warnings=("adapter_not_connected",),
            error_code=ReasonCode.TOOL_FAILURE,
        )


__all__ = ["ToolAdapter", "UnavailableToolAdapter", "query_fingerprint"]
