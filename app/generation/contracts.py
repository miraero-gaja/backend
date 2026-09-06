"""Typed contracts for evidence-only answer generation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evidence.models import AggregateEvidence, EvidenceItem, ReasonCode, SupportStatus


class GenerationValidationStatus(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    ACCEPTED = "ACCEPTED"
    REJECTED_EMPTY = "REJECTED_EMPTY"
    REJECTED_FORMAT = "REJECTED_FORMAT"
    REJECTED_STATUS = "REJECTED_STATUS"
    REJECTED_ENTITY = "REJECTED_ENTITY"
    REJECTED_NUMBER = "REJECTED_NUMBER"
    REJECTED_UNIT = "REJECTED_UNIT"
    REJECTED_RECOMMENDATION = "REJECTED_RECOMMENDATION"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"


class GenerationValidationReason(StrEnum):
    """Safe internal detail for coarse generation validation statuses."""

    NON_JSON_OUTPUT = "NON_JSON_OUTPUT"
    INVALID_JSON_SHAPE = "INVALID_JSON_SHAPE"
    MISSING_EVIDENCE_PLACEHOLDER = "MISSING_EVIDENCE_PLACEHOLDER"
    ANSWER_LENGTH_INVALID = "ANSWER_LENGTH_INVALID"
    MARKDOWN_JSON_WRAPPER = "MARKDOWN_JSON_WRAPPER"
    FORMAT_REPAIR_ACCEPTED = "FORMAT_REPAIR_ACCEPTED"
    EVIDENCE_LITERAL_NORMALIZED = "EVIDENCE_LITERAL_NORMALIZED"
    UNKNOWN_PLACEHOLDER = "UNKNOWN_PLACEHOLDER"
    ENTITY_MARKER_ROLE_MISMATCH = "ENTITY_MARKER_ROLE_MISMATCH"
    LITERAL_EVIDENCE_ENTITY = "LITERAL_EVIDENCE_ENTITY"
    UNMARKED_IDENTIFIER = "UNMARKED_IDENTIFIER"
    UNMARKED_PRODUCT_REFERENCE = "UNMARKED_PRODUCT_REFERENCE"
    UNSUPPORTED_FINANCIAL_CLAIM = "UNSUPPORTED_FINANCIAL_CLAIM"
    ENTITY_IN_UNSUPPORTED_RESPONSE = "ENTITY_IN_UNSUPPORTED_RESPONSE"
    TRANSPORT_EXCEPTION = "TRANSPORT_EXCEPTION"
    TRANSPORT_OPEN_TIMEOUT = "TRANSPORT_OPEN_TIMEOUT"
    TRANSPORT_READ_TIMEOUT = "TRANSPORT_READ_TIMEOUT"
    TRANSPORT_HTTP_ERROR = "TRANSPORT_HTTP_ERROR"
    TRANSPORT_RESPONSE_PARSE = "TRANSPORT_RESPONSE_PARSE"
    TRANSPORT_CONNECTION_ERROR = "TRANSPORT_CONNECTION_ERROR"


class GenerationInput(BaseModel):
    """Only validated public facts may cross the generation boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str
    support_status: SupportStatus
    reason_codes: tuple[ReasonCode, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    aggregate_evidence: tuple[AggregateEvidence, ...] = ()
    execution_trace: str = Field(max_length=200)
    deterministic_fallback_answer: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def evidence_must_already_be_validated(self) -> "GenerationInput":
        if any(item.decision is not SupportStatus.SUPPORTED for item in self.evidence):
            raise ValueError("generation input accepts only supported evidence")
        if any(
            item.decision is not SupportStatus.SUPPORTED
            for item in self.aggregate_evidence
        ):
            raise ValueError("generation input accepts only supported aggregate evidence")
        return self

    @classmethod
    def from_decision(
        cls,
        *,
        question: str,
        decision_status: SupportStatus,
        reason_codes: tuple[ReasonCode, ...],
        evidence: tuple[EvidenceItem, ...],
        aggregate_evidence: tuple[AggregateEvidence, ...] = (),
        execution_trace: str,
        deterministic_fallback_answer: str,
    ) -> "GenerationInput":
        return cls(
            question=question,
            support_status=decision_status,
            reason_codes=reason_codes,
            evidence=tuple(
                item
                for item in evidence
                if item.decision is SupportStatus.SUPPORTED
            ),
            aggregate_evidence=tuple(
                item
                for item in aggregate_evidence
                if item.decision is SupportStatus.SUPPORTED
            ),
            execution_trace=execution_trace,
            deterministic_fallback_answer=deterministic_fallback_answer,
        )


class GenerationResult(BaseModel):
    """Generated answer plus internal, non-public execution metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=1000)
    provider: str = Field(min_length=1)
    used_fallback: bool
    validation_status: GenerationValidationStatus
    validation_reason: GenerationValidationReason | None = None
    transport_error_code: str | None = None
    transport_exception_class: str | None = None
    transport_http_status: int | None = Field(default=None, ge=100, le=599)
    transport_ncp_status_code: str | None = Field(default=None, max_length=64)
    elapsed_ms: float = Field(ge=0)


__all__ = [
    "GenerationInput",
    "GenerationResult",
    "GenerationValidationReason",
    "GenerationValidationStatus",
]
