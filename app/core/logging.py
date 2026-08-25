"""Small JSON logging layer that deliberately omits raw questions and secrets."""

import json
import logging as stdlib_logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

LOGGER_NAMESPACE = "mirae_financial_agent"


@dataclass(frozen=True, slots=True)
class LogFields:
    """Operational fields approved for request-level structured logs."""

    request_id: str | None = None
    question_id: str | None = None
    route: str | None = None
    elapsed_ms: float | None = None
    support_status: str | None = None
    error_code: str | None = None
    generation_provider: str | None = None
    generation_used_fallback: bool | None = None
    generation_validation_status: str | None = None
    generation_elapsed_ms: float | None = None

    def as_extra(self) -> dict[str, Any]:
        return asdict(self)


class JsonFormatter(stdlib_logging.Formatter):
    """Render a fixed allowlist of fields rather than arbitrary record data."""

    def format(self, record: stdlib_logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in LogFields.__dataclass_fields__:
            payload[field_name] = getattr(record, field_name, None)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> None:
    """Configure only this application namespace and remain import-idempotent."""

    # Uvicorn's standard access logger includes the complete query string. The
    # official endpoint carries the raw question in that query string, so the
    # application disables it and emits the allowlisted event below instead.
    stdlib_logging.getLogger("uvicorn.access").disabled = True
    logger = stdlib_logging.getLogger(LOGGER_NAMESPACE)
    logger.setLevel(level)
    logger.propagate = False
    if not any(getattr(handler, "_mirae_json_handler", False) for handler in logger.handlers):
        handler = stdlib_logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._mirae_json_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    for handler in logger.handlers:
        handler.setLevel(level)


def get_logger(name: str) -> stdlib_logging.Logger:
    return stdlib_logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")
