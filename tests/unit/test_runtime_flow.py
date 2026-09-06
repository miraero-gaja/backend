"""Safety checks for the no-evidence runtime path and deadline boundary."""

import asyncio

import app.agent.executor as executor_module
from app.agent.contracts import QueryContract, RouteHint, ToolResult
from app.agent.executor import ToolExecutor
from app.agent.grounder import OntologyGrounder
from app.core.deadline import Deadline
from app.evidence.models import ReasonCode, SupportStatus
from app.evidence.validator import EvidenceValidator
from app.tools.structured import StructuredToolAdapter
from app.structured import AggregateFunction, StructuredQueryContract


class SlowAdapter:
    """Test adapter that can finish only if the executor fails to enforce time."""

    tool_name = "slow-test-adapter"

    async def execute(
        self,
        query: QueryContract,
        deadline: Deadline,
    ) -> ToolResult:
        del query, deadline
        await asyncio.sleep(1)
        raise AssertionError("deadline did not stop the adapter")


def _query(route_hint: RouteHint = RouteHint.UNSUPPORTED) -> QueryContract:
    return QueryContract(
        request_id="runtime-flow-request",
        question_id="runtime-flow-question",
        route_hint=route_hint,
    )


def test_no_evidence_is_an_unavailable_tool_not_an_out_of_scope_claim() -> None:
    decision = EvidenceValidator().validate(_query(), ())

    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.reason_codes == (ReasonCode.TOOL_FAILURE,)


def test_executor_enforces_deadline_around_adapter() -> None:
    query = _query(RouteHint.STRUCTURED)
    executor = ToolExecutor({RouteHint.STRUCTURED: SlowAdapter()})

    results = asyncio.run(
        executor.execute(query, RouteHint.STRUCTURED, Deadline.after(0.01))
    )

    assert len(results) == 1
    assert results[0].error_code is ReasonCode.TOOL_FAILURE
    assert results[0].warnings == ("deadline_exceeded",)


def test_executor_logs_only_safe_exception_metadata(monkeypatch) -> None:
    class FailingAdapter:
        tool_name = "structured"

        async def execute(self, query, deadline):
            del query, deadline
            raise RuntimeError("must-not-appear: postgresql://user:secret@host/db")

    class RecordingLogger:
        def __init__(self) -> None:
            self.calls = []

        def error(self, message, *, extra) -> None:
            self.calls.append((message, extra))

    logger = RecordingLogger()
    monkeypatch.setattr(executor_module, "logger", logger)
    query = _query(RouteHint.STRUCTURED)
    executor = ToolExecutor({RouteHint.STRUCTURED: FailingAdapter()})

    results = asyncio.run(
        executor.execute(query, RouteHint.STRUCTURED, Deadline.after(1))
    )

    assert results[0].error_code is ReasonCode.TOOL_FAILURE
    assert results[0].warnings == ("tool_execution_failed",)
    assert logger.calls == [
        (
            "tool_execution_failed",
            {
                "request_id": query.request_id,
                "question_id": None,
                "route": "structured",
                "elapsed_ms": None,
                "support_status": None,
                "error_code": "TOOL_EXECUTION_FAILED",
                "exception_class": "RuntimeError",
                "generation_provider": None,
                "generation_used_fallback": None,
                "generation_validation_status": None,
                "generation_validation_reason": None,
                "generation_transport_error_code": None,
                "generation_transport_exception_class": None,
                "generation_transport_http_status": None,
                "generation_transport_ncp_status_code": None,
                "generation_elapsed_ms": None,
            },
        )
    ]
    assert "secret" not in repr(logger.calls)


def test_unconnected_tool_adapter_returns_no_candidates() -> None:
    result = asyncio.run(
        StructuredToolAdapter().execute(_query(), Deadline.after(1))
    )

    assert result.candidates == ()
    assert result.error_code is ReasonCode.TOOL_FAILURE
    assert result.warnings == ("adapter_not_connected",)


def test_only_an_explicit_unambiguous_structured_plan_is_grounded() -> None:
    explicit = _query().model_copy(
        update={
            "structured_query": StructuredQueryContract(
                product_scope="PREF01N001",
                aggregate=AggregateFunction.COUNT,
            )
        }
    )

    assert OntologyGrounder().ground(explicit).route_hint is RouteHint.STRUCTURED
    assert OntologyGrounder().ground(_query()).route_hint is RouteHint.UNSUPPORTED
