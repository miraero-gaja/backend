"""Public response schemas for the official evaluation API."""

from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse


class Utf8JSONResponse(JSONResponse):
    """JSON response with the charset required by the evaluation contract."""

    media_type = "application/json; charset=utf-8"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


class AnswerResponse(BaseModel):
    """The exact five-string-field response contract for ``GET /answer``."""

    model_config = ConfigDict(extra="forbid")
    question_id: str
    question: str
    retrieved_context: str
    think_trace: str
    answer: str

