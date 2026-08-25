"""Official GET /answer endpoint backed by the deterministic Core pipeline."""

from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.agent.executor import ToolExecutor
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.agent.router import QueryRouter
from app.api.answer_renderer import DeterministicAnswerRenderer
from app.api.schemas import AnswerResponse, Utf8JSONResponse
from app.composition import get_answer_generator, get_tool_executor
from app.core.config import Settings, get_settings
from app.core.deadline import Deadline
from app.core.logging import LogFields, get_logger
from app.evidence.validator import EvidenceValidator
from app.generation import AnswerGenerator, GenerationInput

router = APIRouter()
logger = get_logger(__name__)
parser = QueryParser()
grounder = OntologyGrounder()
query_router = QueryRouter()
evidence_validator = EvidenceValidator()
answer_renderer = DeterministicAnswerRenderer()


@router.get("/answer", response_model=AnswerResponse, response_class=Utf8JSONResponse)
async def answer(
    request: Request,
    question_id: Annotated[str, Query(description="Evaluation question identifier")],
    question: Annotated[str, Query(description="Question text echoed unchanged")],
    settings: Annotated[Settings, Depends(get_settings)],
    tool_executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
    answer_generator: Annotated[AnswerGenerator, Depends(get_answer_generator)],
) -> AnswerResponse:
    """Execute the Core pipeline and render only deterministic validated facts."""

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
    rendered = answer_renderer.render(grounded_query, decision)
    generation_input = GenerationInput.from_decision(
        question=question,
        decision_status=decision.status,
        reason_codes=decision.reason_codes,
        evidence=decision.evidence,
        execution_trace=rendered.think_trace,
        deterministic_fallback_answer=rendered.answer,
    )
    generation_result = await answer_generator.generate(generation_input)

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
            generation_provider=generation_result.provider,
            generation_used_fallback=generation_result.used_fallback,
            generation_validation_status=generation_result.validation_status.value,
            generation_elapsed_ms=round(generation_result.elapsed_ms, 3),
        ).as_extra(),
    )
    return AnswerResponse(
        question_id=question_id,
        question=question,
        retrieved_context=rendered.retrieved_context,
        think_trace=rendered.think_trace,
        answer=generation_result.answer,
    )
