"""Safe errors, preserving the five-field contract for ``GET /answer``."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import AnswerResponse, Utf8JSONResponse
from app.core.constants import NO_EVIDENCE_CONTEXT, UNSUPPORTED_ANSWER, missing_input_answer, missing_input_trace
from app.core.logging import LogFields, get_logger

logger = get_logger(__name__)


def _answer_error(request: Request, missing: tuple[str, ...]) -> Utf8JSONResponse:
    question_id = request.query_params.get("question_id", "")
    question = request.query_params.get("question", "")
    body = AnswerResponse(
        question_id=question_id,
        question=question,
        retrieved_context=NO_EVIDENCE_CONTEXT,
        think_trace=(
            missing_input_trace(missing)
            if missing
            else "입력 검증 → 내부 처리 실패 확인 → Unsupported 처리"
        ),
        answer=missing_input_answer(missing) if missing else UNSUPPORTED_ANSWER,
    )
    logger.warning(
        "answer_request_failed",
        extra=LogFields(
            request_id=getattr(request.state, "request_id", "unavailable"),
            question_id=question_id,
            route="unsupported",
            support_status="UNSUPPORTED",
            error_code=("MISSING_REQUIRED_INPUT" if missing else "TOOL_FAILURE"),
        ).as_extra(),
    )
    return Utf8JSONResponse(status_code=200, content=body.model_dump())


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Utf8JSONResponse:
        if request.url.path == "/answer" and request.method == "GET":
            missing = tuple(
                field
                for field in ("question_id", "question")
                if any(
                    error.get("type") == "missing"
                    and tuple(error.get("loc", ())) == ("query", field)
                    for error in exc.errors()
                )
            )
            return _answer_error(request, missing)
        return Utf8JSONResponse(
            status_code=422,
            content={"error_code": "REQUEST_VALIDATION_ERROR", "message": "Request validation failed."},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Utf8JSONResponse:
        if request.url.path == "/answer" and request.method == "GET":
            return _answer_error(request, ())
        return Utf8JSONResponse(
            status_code=exc.status_code,
            content={"error_code": "HTTP_ERROR", "message": "Request failed."},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> Utf8JSONResponse:
        del exc
        if request.url.path == "/answer" and request.method == "GET":
            return _answer_error(request, ())
        logger.error(
            "unhandled_request_failure",
            extra=LogFields(
                request_id=getattr(request.state, "request_id", "unavailable"),
                error_code="TOOL_FAILURE",
            ).as_extra(),
        )
        return Utf8JSONResponse(
            status_code=500,
            content={"error_code": "INTERNAL_ERROR", "message": "Request failed."},
        )
