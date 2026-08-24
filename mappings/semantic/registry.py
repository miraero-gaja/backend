"""Evidence-gated semantic approvals kept separate from the G2 registry.

This module records reviewed semantic claims even when no runtime operation is
approved. It does not feed or mutate the G2 trusted-query allowlist. Callers
must use ``SemanticFieldApproval.open_operations`` and must not infer an
operation from a confirmed concept alone.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from .models import (
    ClaimStatus,
    EvidenceProvenance,
    EvidenceTier,
    EvidenceType,
    OperationApproval,
    OperationStatus,
    SemanticClaim,
    SemanticFieldApproval,
)


_RUNTIME_NUMERIC_OPERATIONS = (
    "EQ",
    "NE",
    "LT",
    "LE",
    "GT",
    "GE",
    "SORT_ASC",
    "SORT_DESC",
)

_PREF02_SOURCE_SHA256 = (
    "3cec19043f742771e0016d56fe806f19"
    "ad78f4295d1ae59192740a78feb2253b"
)
_PRBD_SOURCE_SHA256 = (
    "728f44a567a986d21cf843d711c6c4d"
    "fa1a24d05b39c7da0541b981b57ecccf8"
)


def _profile_provenance(
    *,
    artifact_relative_path: str,
    logical_table_id: str,
    source_column: str,
    source_identity: str,
    rationale: str,
) -> EvidenceProvenance:
    return EvidenceProvenance(
        evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
        artifact_relative_path=artifact_relative_path,
        source_logical_table=logical_table_id,
        source_column=source_column,
        source_identity=source_identity,
        evidence_type=EvidenceType.PROFILE_ARTIFACT,
        rationale=rationale,
        reproducible=True,
    )


def _closed_operations(
    operations: Iterable[str],
    *,
    reason: str,
) -> tuple[OperationApproval, ...]:
    return tuple(
        OperationApproval(
            operation=operation,
            status=OperationStatus.CLOSED,
            reason=reason,
        )
        for operation in operations
    )


SEMANTIC_FIELD_APPROVALS: tuple[SemanticFieldApproval, ...] = (
    SemanticFieldApproval(
        logical_table_id="PREF02N001",
        source_column="cu_charge_rt",
        semantic_key="pref02.expense_ratio",
        concept=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T2_OFFICIAL_SIBLING_SCHEMA,
            evidence=(
                "The PREF01N001 official sibling schema identifies the same "
                "source column as a total expense-ratio concept. T2 transfers "
                "the concept only."
            ),
        ),
        unit=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=None,
            evidence="The PREF02N001 unit and scale are not officially confirmed.",
        ),
        value_domain=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence=(
                "The profile records only the source-native distribution. The "
                "unit, scale, and meaning of zero are not officially confirmed."
            ),
            provenance=(
                _profile_provenance(
                    artifact_relative_path=(
                        "artifacts/profiling/g3a1_pref02/g1_data_profile.json"
                    ),
                    logical_table_id="PREF02N001",
                    source_column="cu_charge_rt",
                    source_identity=_PREF02_SOURCE_SHA256,
                    rationale=(
                        "Records parseability and min/max without assigning a "
                        "unit, scale, or meaning to zero."
                    ),
                ),
            ),
        ),
        operations=_closed_operations(
            _RUNTIME_NUMERIC_OPERATIONS,
            reason=(
                "Runtime numeric use is closed until the PREF02N001 unit, "
                "scale, and value domain are approved."
            ),
        ),
        notes=(
            "Concept approval must not be treated as numeric-operation approval."
        ),
    ),
    SemanticFieldApproval(
        logical_table_id="PREF02N001",
        source_column="du_last_aum",
        semantic_key="pref02.aum_latest",
        concept=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T2_OFFICIAL_SIBLING_SCHEMA,
            evidence=(
                "The PREF01N001 official sibling schema identifies the same "
                "source column as latest AUM. T2 transfers the concept only."
            ),
        ),
        unit=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=None,
            evidence="The PREF02N001 AUM unit and scale are not officially confirmed.",
        ),
        value_domain=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence=(
                "The retained G1 profile at artifacts/profiling/g3a1_pref02/"
                "g1_data_profile.json records 5,459/5,459 nonblank values as "
                "finite Decimal-parseable source strings, 187 missing values, "
                "zero empty/whitespace/error/formula values, and exact Decimal "
                "ordering candidacy."
            ),
            provenance=(
                _profile_provenance(
                    artifact_relative_path=(
                        "artifacts/profiling/g3a1_pref02/g1_data_profile.json"
                    ),
                    logical_table_id="PREF02N001",
                    source_column="du_last_aum",
                    source_identity=_PREF02_SOURCE_SHA256,
                    rationale=(
                        "Reproduces complete finite Decimal parsing and exact "
                        "source-native ordering with explicit null handling."
                    ),
                ),
            ),
        ),
        operations=(
            OperationApproval(
                operation="SORT_DESC",
                status=OperationStatus.OPEN,
                reason=(
                    "Source-native Decimal ranking needs no unit conversion; "
                    "missing values sort last and source_row_id breaks ties."
                ),
                evidence=(
                    "artifacts/profiling/g3a1_pref02/g1_data_profile.json "
                    "PREF02N001.du_last_aum#1; app/structured/compiler.py "
                    "orders DESC NULLS LAST then source_row_id ASC."
                ),
                provenance=(
                    _profile_provenance(
                        artifact_relative_path=(
                            "artifacts/profiling/g3a1_pref02/"
                            "g1_data_profile.json"
                        ),
                        logical_table_id="PREF02N001",
                        source_column="du_last_aum",
                        source_identity=_PREF02_SOURCE_SHA256,
                        rationale=(
                            "Supports unit-free source-native descending rank; "
                            "absolute thresholds remain outside approval."
                        ),
                    ),
                ),
            ),
            *_closed_operations(
                ("LT", "LE", "GT", "GE"),
                reason=(
                    "Absolute threshold comparison requires an approved AUM "
                    "unit and scale."
                ),
            ),
        ),
        notes=(
            "SORT_DESC is OPEN from reproducible source-native profiling; "
            "absolute thresholds remain closed until unit approval."
        ),
    ),
    *(
        SemanticFieldApproval(
            logical_table_id="PRBD01N001",
            source_column=source_column,
            semantic_key=semantic_key,
            concept=SemanticClaim(
                status=ClaimStatus.UNKNOWN,
                evidence_tier=None,
                evidence=(
                    "The official financial meaning and direction are not "
                    "approved; the source name is not treated as semantics."
                ),
            ),
            unit=SemanticClaim(
                status=ClaimStatus.UNKNOWN,
                evidence_tier=None,
                evidence="The official unit and scale are not confirmed.",
            ),
            value_domain=SemanticClaim(
                status=ClaimStatus.NEED_REVIEW,
                evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
                evidence=(
                    "The retained profile records source-native distribution "
                    "only and does not approve financial meaning."
                ),
                provenance=(
                    _profile_provenance(
                        artifact_relative_path=(
                            "artifacts/profiling/g3a1_prbd/"
                            "g1_data_profile.json"
                        ),
                        logical_table_id="PRBD01N001",
                        source_column=source_column,
                        source_identity=_PRBD_SOURCE_SHA256,
                        rationale=(
                            "Records row/null/distinct, parseability, and bounded "
                            "source-native distribution without semantic inference."
                        ),
                    ),
                ),
            ),
            operations=_closed_operations(
                _RUNTIME_NUMERIC_OPERATIONS,
                reason=(
                    "Runtime operations remain closed until official concept, "
                    "direction, unit, and value-domain semantics are approved."
                ),
            ),
            notes=(
                "T4 profiling establishes reproducible observations only; it "
                "does not establish the field's financial interpretation."
            ),
        )
        for source_column, semantic_key in (
            ("PD_RISK_GCD", "prbd.pd_risk_gcd_unresolved"),
            ("DUR", "prbd.dur_unresolved"),
            ("NDY_DUR", "prbd.ndy_dur_unresolved"),
            ("COV", "prbd.cov_unresolved"),
        )
    ),
)


def validate_semantic_registry(
    approvals: Iterable[SemanticFieldApproval],
) -> None:
    """Reject ambiguous semantic keys and source identities."""

    records = tuple(approvals)
    semantic_identities = [
        (approval.logical_table_id, approval.semantic_key)
        for approval in records
    ]
    duplicate_semantic_keys = sorted(
        f"{table_id}.{semantic_key}"
        for (table_id, semantic_key), count in Counter(semantic_identities).items()
        if count > 1
    )
    source_identities = [
        (approval.logical_table_id, approval.qualified_name)
        for approval in records
    ]
    duplicate_source_identities = sorted(
        f"{table_id}.{qualified_name}"
        for (table_id, qualified_name), count in Counter(source_identities).items()
        if count > 1
    )
    if duplicate_semantic_keys:
        raise ValueError(
            f"duplicate semantic approvals: {duplicate_semantic_keys}"
        )
    if duplicate_source_identities:
        raise ValueError(
            f"duplicate source identities: {duplicate_source_identities}"
        )


def _build_lookup(
    approvals: Iterable[SemanticFieldApproval],
) -> Mapping[tuple[str, str], SemanticFieldApproval]:
    records = tuple(approvals)
    validate_semantic_registry(records)
    return MappingProxyType(
        {
            (approval.logical_table_id, approval.semantic_key): approval
            for approval in records
        }
    )


_APPROVALS_BY_TABLE_AND_KEY = _build_lookup(SEMANTIC_FIELD_APPROVALS)


def get_semantic_field_approval(
    logical_table_id: str,
    semantic_key: str,
) -> SemanticFieldApproval | None:
    """Return one table-scoped approval, or ``None`` for an unknown key."""

    return _APPROVALS_BY_TABLE_AND_KEY.get((logical_table_id, semantic_key))


def get_table_semantic_approvals(
    logical_table_id: str,
) -> tuple[SemanticFieldApproval, ...]:
    """Return reviewed approvals for one table in deterministic registry order."""

    return tuple(
        approval
        for approval in SEMANTIC_FIELD_APPROVALS
        if approval.logical_table_id == logical_table_id
    )


__all__ = [
    "SEMANTIC_FIELD_APPROVALS",
    "get_semantic_field_approval",
    "get_table_semantic_approvals",
    "validate_semantic_registry",
]
