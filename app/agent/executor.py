"""Deadline-aware dispatch to explicitly registered retrieval adapters."""

from collections.abc import Mapping

from app.agent.contracts import QueryContract, RouteHint, ToolResult
from app.core.deadline import Deadline, DeadlineExceeded
from app.core.logging import LogFields, get_logger
from app.evidence.models import ReasonCode
from app.tools import ToolAdapter, query_fingerprint
from app.tools.cost_rules import CostRulesToolAdapter
from app.tools.graph import GraphToolAdapter
from app.tools.structured import StructuredToolAdapter
from app.tools.vector import VectorToolAdapter


logger = get_logger(__name__)


class ToolExecutor:
    """Execute only the selected tool and convert failures to typed results."""

    def __init__(self, adapters: Mapping[RouteHint, ToolAdapter] | None = None) -> None:
        self._adapters = (
            adapters
            if adapters is not None
            else {
                RouteHint.STRUCTURED: StructuredToolAdapter(),
                RouteHint.GRAPH: GraphToolAdapter(),
                RouteHint.VECTOR: VectorToolAdapter(),
                RouteHint.COST_RULES: CostRulesToolAdapter(),
            }
        )

    async def execute(
        self,
        query: QueryContract,
        route: RouteHint,
        deadline: Deadline,
    ) -> tuple[ToolResult, ...]:
        if route is RouteHint.UNSUPPORTED:
            return ()
        adapter = self._adapters.get(route)
        if adapter is None:
            return (self._failure(query, route.value, "adapter_not_registered"),)
        try:
            return (
                await deadline.run(lambda: adapter.execute(query, deadline)),
            )
        except DeadlineExceeded:
            return (self._failure(query, adapter.tool_name, "deadline_exceeded"),)
        except Exception as error:
            logger.error(
                "tool_execution_failed",
                extra=LogFields(
                    request_id=query.request_id,
                    route=route.value,
                    error_code="TOOL_EXECUTION_FAILED",
                    exception_class=type(error).__name__,
                ).as_extra(),
            )
            return (self._failure(query, adapter.tool_name, "tool_execution_failed"),)

    @staticmethod
    def _failure(query: QueryContract, tool_name: str, warning: str) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            query_fingerprint=query_fingerprint(query),
            warnings=(warning,),
            error_code=ReasonCode.TOOL_FAILURE,
        )
