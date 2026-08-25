"""FastAPI application factory for the backend foundation."""

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from app import __version__
from app.api.exception_handlers import install_exception_handlers
from app.api.routes import router
from app.api.schemas import Utf8JSONResponse
from app.composition import build_application_runtime
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.generation import AnswerGenerator
from app.structured import AsyncQueryBackend


def create_app(
    *,
    settings: Settings | None = None,
    structured_backend: AsyncQueryBackend | None = None,
    structured_schema_path: str | Path | None = None,
    answer_generator: AnswerGenerator | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    runtime = build_application_runtime(
        resolved_settings,
        structured_backend=structured_backend,
        structured_schema_path=structured_schema_path,
        answer_generator=answer_generator,
    )
    application = FastAPI(
        title="Mirae Asset Financial Product Agent",
        version=__version__,
        default_response_class=Utf8JSONResponse,
    )
    application.state.runtime = runtime

    @application.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    install_exception_handlers(application)
    application.include_router(router)
    return application


app = create_app()
