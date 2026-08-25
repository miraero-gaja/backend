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
    elapsed_ms: float = Field(ge=0)


__all__ = [
    "GenerationInput",
    "GenerationResult",
    "GenerationValidationStatus",
]
