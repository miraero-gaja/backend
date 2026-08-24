"""Evidence-aware semantic mapping contracts for G3.

G3 separates concept meaning, unit knowledge, value-domain knowledge,
operation approval, and provenance.  A concept may be understood while
specific numerical or coded operations remain closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class EvidenceTier(StrEnum):
    """Strength of evidence supporting a semantic claim."""

    T1_OFFICIAL_SCHEMA = "T1_OFFICIAL_SCHEMA"
    T2_OFFICIAL_SIBLING_SCHEMA = "T2_OFFICIAL_SIBLING_SCHEMA"
    T3_TEAM_TRIANGULATED_EVIDENCE = "T3_TEAM_TRIANGULATED_EVIDENCE"
    T4_INTERNAL_REPRODUCIBLE_VALIDATION = "T4_INTERNAL_REPRODUCIBLE_VALIDATION"


class ClaimStatus(StrEnum):
    """Approval state for an individual semantic claim."""

    CONFIRMED = "CONFIRMED"
    NEED_REVIEW = "NEED_REVIEW"
    UNKNOWN = "UNKNOWN"


class OperationStatus(StrEnum):
    """Whether an operation is safe for runtime use."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EvidenceType(StrEnum):
    """Machine-readable kind of evidence behind a semantic decision."""

    OFFICIAL_SCHEMA = "OFFICIAL_SCHEMA"
    SIBLING_SCHEMA = "SIBLING_SCHEMA"
    PROFILE_ARTIFACT = "PROFILE_ARTIFACT"
    INTERNAL_VALIDATION = "INTERNAL_VALIDATION"


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    """Reproducible reference that complements human-readable evidence text."""

    evidence_tier: EvidenceTier
    artifact_relative_path: str
    source_logical_table: str
    source_column: str
    source_identity: str
    evidence_type: EvidenceType
    rationale: str
    reproducible: bool = False

    def __post_init__(self) -> None:
        if not self.source_logical_table.strip():
            raise ValueError("provenance source table must not be blank")
        if not self.source_column.strip():
            raise ValueError("provenance source column must not be blank")
        if not self.source_identity.strip():
            raise ValueError("provenance source identity must not be blank")
        if not self.rationale.strip():
            raise ValueError("provenance rationale must not be blank")

        artifact_path = self.artifact_relative_path.strip()
        if (
            self.evidence_type is EvidenceType.PROFILE_ARTIFACT
            and not artifact_path
        ):
            raise ValueError(
                "PROFILE_ARTIFACT provenance requires an artifact relative path"
            )
        if artifact_path:
            path = PurePosixPath(artifact_path.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
                raise ValueError("provenance artifact path must be repo-relative")

    @property
    def is_reproducible_artifact(self) -> bool:
        return bool(
            self.reproducible
            and self.artifact_relative_path.strip()
            and self.evidence_type
            in {EvidenceType.PROFILE_ARTIFACT, EvidenceType.INTERNAL_VALIDATION}
        )


@dataclass(frozen=True, slots=True)
class SemanticClaim:
    """One independently evidenced claim about a source field."""

    status: ClaimStatus
    evidence_tier: EvidenceTier | None
    evidence: str
    provenance: tuple[EvidenceProvenance, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.status is ClaimStatus.CONFIRMED
            and self.evidence_tier
            is EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION
            and not any(
                item.evidence_tier
                is EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION
                and item.is_reproducible_artifact
                for item in self.provenance
            )
        ):
            raise ValueError(
                "T4 CONFIRMED claim requires reproducible artifact provenance"
            )


@dataclass(frozen=True, slots=True)
class OperationApproval:
    """Runtime approval for one deterministic operation."""

    operation: str
    status: OperationStatus
    reason: str
    evidence: str = ""
    provenance: tuple[EvidenceProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must not be blank")
        if not self.reason.strip():
            raise ValueError("operation reason must not be blank")
        if self.status is OperationStatus.OPEN and not self.evidence.strip():
            raise ValueError("OPEN operation must have non-empty evidence")
        if self.status is OperationStatus.OPEN and not any(
            item.is_reproducible_artifact for item in self.provenance
        ):
            raise ValueError(
                "OPEN operation requires reproducible artifact provenance"
            )


@dataclass(frozen=True, slots=True)
class SemanticFieldApproval:
    """Evidence-aware semantic approval for one source column."""

    logical_table_id: str
    source_column: str
    semantic_key: str

    concept: SemanticClaim
    unit: SemanticClaim
    value_domain: SemanticClaim

    operations: tuple[OperationApproval, ...]

    notes: str = ""

    def __post_init__(self) -> None:
        provenance = (
            *self.concept.provenance,
            *self.unit.provenance,
            *self.value_domain.provenance,
            *(
                item
                for operation in self.operations
                for item in operation.provenance
            ),
        )
        for item in provenance:
            if item.source_logical_table != self.logical_table_id:
                raise ValueError(
                    "provenance source table conflicts with approval identity"
                )
            if item.source_column != self.source_column:
                raise ValueError(
                    "provenance source column conflicts with approval identity"
                )

        open_operations = tuple(
            approval
            for approval in self.operations
            if approval.status is OperationStatus.OPEN
        )
        if open_operations and self.concept.status is ClaimStatus.UNKNOWN:
            raise ValueError("concept UNKNOWN cannot have an OPEN operation")
        if (
            any(approval.operation == "SORT_DESC" for approval in open_operations)
            and self.value_domain.status is not ClaimStatus.CONFIRMED
        ):
            raise ValueError(
                "SORT_DESC OPEN requires a CONFIRMED value_domain"
            )
        operation_names = [approval.operation for approval in self.operations]
        if len(set(operation_names)) != len(operation_names):
            raise ValueError("operations must not contain duplicates")

    @property
    def qualified_name(self) -> str:
        return f"{self.source_column}#1"

    @property
    def open_operations(self) -> tuple[str, ...]:
        return tuple(
            approval.operation
            for approval in self.operations
            if approval.status is OperationStatus.OPEN
        )
