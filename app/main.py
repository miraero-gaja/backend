"""FastAPI application factory for the backend foundation."""

from uuid import uuid4

from fastapi import FastAPI, Request, Response

from app import __version__
from app.api.exception_handlers import install_exception_handlers
from app.api.routes import router
from app.api.schemas import Utf8JSONResponse
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(
        title="Mirae Asset Financial Product Agent",
        version=__version__,
        default_response_class=Utf8JSONResponse,
    )

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

