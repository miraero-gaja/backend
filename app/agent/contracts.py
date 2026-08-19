"""Typed runtime contracts shared by parsing, routing, and tool adapters."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.models import ReasonCode, ScalarValue


class RouteHint(StrEnum):
    UNSUPPORTED = "unsupported"
    STRUCTURED = "structured"
    GRAPH = "graph"
    VECTOR = "vector"
    COST_RULES = "cost_rules"


class QueryContract(BaseModel):
    """A generic execution plan that does not presume dataset columns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    question_id: str
    product_scopes: tuple[str, ...] = ()
    filters: dict[str, ScalarValue] = Field(default_factory=dict)
    projections: tuple[str, ...] = ()
    sort: tuple[str, ...] = ()
    limit: int | None = Field(default=None, gt=0)
    semantic_intent: str | None = None
    ambiguity: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    route_hint: RouteHint = RouteHint.UNSUPPORTED


class ToolResult(BaseModel):
    """Schema-neutral result envelope returned by every retrieval adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    query_fingerprint: str
    candidates: tuple[dict[str, ScalarValue], ...] = ()
    columns: tuple[str, ...] = ()
    elapsed_ms: float = Field(default=0.0, ge=0)
    warnings: tuple[str, ...] = ()
    error_code: ReasonCode | None = None

