"""Official answer endpoint using the deterministic safe skeleton response."""

from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.agent.executor import ToolExecutor
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.agent.router import QueryRouter
from app.api.schemas import AnswerResponse, Utf8JSONResponse
from app.composition import get_tool_executor
from app.core.config import Settings, get_settings
from app.core.constants import UNSUPPORTED_TRACE, missing_input_trace
from app.core.deadline import Deadline, DeadlineExceeded
from app.core.logging import LogFields, get_logger
from app.evidence.models import ReasonCode, SupportDecision, SupportStatus
from app.evidence.serializer import serialize_evidence
from app.evidence.validator import EvidenceValidator
from app.llm.answer_guard import AnswerGuard
from app.llm.hcx_client import HCXUnavailableError, build_hcx_client
from app.llm.prompts import build_grounded_prompt

router = APIRouter()
logger = get_logger(__name__)
parser = QueryParser()
grounder = OntologyGrounder()
query_router = QueryRouter()
evidence_validator = EvidenceValidator()
answer_guard = AnswerGuard()


@router.get("/answer", response_model=AnswerResponse, response_class=Utf8JSONResponse)
async def answer(
    request: Request,
    question_id: Annotated[str, Query(description="Evaluation question identifier")],
    question: Annotated[str, Query(description="Question text echoed unchanged")],
    settings: Annotated[Settings, Depends(get_settings)],
    tool_executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
) -> AnswerResponse:
    """Fail closed until dataset retrieval and HCX generation are connected."""

    started_at = monotonic()
    request_id = request.state.request_id
    deadline = Deadline.after(settings.answer_deadline_seconds)
    query = parser.parse(
        request_id=request_id,
        question_id=question_id,
        question=question,
    )
    grounded_query = grounder.ground(query)
    route = query_router.route(grounded_query)
    tool_results = await tool_executor.execute(grounded_query, route, deadline)
    evidence = tuple(item for result in tool_results for item in result.evidence)
    decision = evidence_validator.validate(grounded_query, tool_results, evidence)
    retrieved_context = serialize_evidence(decision)

    candidate: str | None = None
    if decision.status is SupportStatus.SUPPORTED and decision.evidence:
        try:
            prompt = build_grounded_prompt(
                question=question,
                retrieved_context=retrieved_context,
            )
            candidate = await deadline.run(
                lambda: build_hcx_client(settings).generate(prompt)
            )
        except (HCXUnavailableError, DeadlineExceeded):
            decision = SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.TOOL_FAILURE,),
                evidence=decision.evidence,
                summary="answer_generation_unavailable",
            )
            retrieved_context = serialize_evidence(decision)

    public_answer = answer_guard.guard(
        candidate,
        decision,
        missing_inputs=grounded_query.required_inputs,
    )
    think_trace = (
        missing_input_trace(grounded_query.required_inputs)
        if grounded_query.required_inputs
        else UNSUPPORTED_TRACE
    )
    error_code = decision.reason_codes[0].value if decision.reason_codes else None
    logger.info(
        "answer_completed",
        extra=LogFields(
            request_id=request_id,
            question_id=question_id,
            route=route.value,
            elapsed_ms=round((monotonic() - started_at) * 1000, 3),
            support_status=decision.status.value,
            error_code=error_code,
        ).as_extra(),
    )
    return AnswerResponse(
        question_id=question_id,
        question=question,
        retrieved_context=retrieved_context,
        think_trace=think_trace,
        answer=public_answer,
    )
