"""Typed runtime contracts shared by parsing, routing, and tool adapters."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.models import AggregateEvidence, EvidenceItem, ReasonCode, ScalarValue
from app.structured.contracts import (
    AggregateFunction,
    FilterOperator,
    SortDirection,
    StructuredQueryContract,
)


class RouteHint(StrEnum):
    UNSUPPORTED = "unsupported"
    STRUCTURED = "structured"
    GRAPH = "graph"
    VECTOR = "vector"
    COST_RULES = "cost_rules"


class QueryUnderstandingStatus(StrEnum):
    PARSED = "PARSED"
    SUPPORTED = "SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"
    RESOLVED_WITH_ASSUMPTION = "RESOLVED_WITH_ASSUMPTION"


class ParsedFilterCondition(BaseModel):
    """Lexically parsed comparison before registry-based semantic approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_alias: str = Field(min_length=1)
    operator: FilterOperator
    value: str = Field(min_length=1)
    unit_token: str | None = None


class QueryUnderstandingResult(BaseModel):
    """Deterministic, concise bridge from natural language to query planning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_candidate: str | None = None
    logical_table_id: str | None = None
    requested_field_alias: str | None = None
    semantic_keys: tuple[str, ...] = ()
    filter_conditions: tuple[ParsedFilterCondition, ...] = ()
    sort_direction: SortDirection | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    aggregate: AggregateFunction | None = None
    status: QueryUnderstandingStatus = QueryUnderstandingStatus.PARSED
    ambiguity: tuple[str, ...] = ()
    unsupported_reason: str | None = None
    execution_trace: tuple[str, ...] = ()


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
    structured_query: StructuredQueryContract | None = None
    understanding: QueryUnderstandingResult | None = None


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
    evidence: tuple[EvidenceItem, ...] = ()
    aggregate_evidence: tuple[AggregateEvidence, ...] = ()
    validation_trace: tuple[str, ...] = ()
