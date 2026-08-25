"""Typed evidence and support decisions independent of any finance schema."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

ScalarValue = str | int | float | bool | None


class SupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    NO_MATCH = "NO_MATCH"


class ReasonCode(StrEnum):
    FIELD_NOT_AVAILABLE = "FIELD_NOT_AVAILABLE"
    MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
    NO_MATCH = "NO_MATCH"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNKNOWN_ENTITY = "UNKNOWN_ENTITY"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    TOOL_FAILURE = "TOOL_FAILURE"


class EvidenceItem(BaseModel):
    """A source-addressable fact; field names remain schema-agnostic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_key: str
    source_table: str
    source_row_id: str
    source_field: str
    raw_value: ScalarValue
    normalized_value: ScalarValue
    unit: str | None = None
    snapshot: str | None = None
    effective_date: date | None = None
    condition_id: str | None = None
    decision: SupportStatus
    formula_id: str | None = None
    ruleset_version: str | None = None


class AggregateEvidence(BaseModel):
    """A validated aggregate result that is not misrepresented as a source row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_table: str
    operation: str = Field(pattern=r"^COUNT$")
    value: int = Field(ge=0)
    query_fingerprint: str
    condition_ids: tuple[str, ...] = ()
    decision: SupportStatus


class SupportDecision(BaseModel):
    """Whether the available evidence supports generating a public answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: SupportStatus
    reason_codes: tuple[ReasonCode, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    aggregate_evidence: tuple[AggregateEvidence, ...] = ()
    summary: str
