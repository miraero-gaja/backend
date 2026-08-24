import pytest

from mappings.semantic.models import (
    ClaimStatus,
    EvidenceProvenance,
    EvidenceTier,
    EvidenceType,
    OperationApproval,
    OperationStatus,
    SemanticClaim,
    SemanticFieldApproval,
)


def _provenance(
    *,
    table: str = "PREF02N001",
    column: str = "du_last_aum",
    artifact_path: str = "artifacts/profiling/test/g1_data_profile.json",
    reproducible: bool = True,
) -> EvidenceProvenance:
    return EvidenceProvenance(
        evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
        artifact_relative_path=artifact_path,
        source_logical_table=table,
        source_column=column,
        source_identity="a" * 64,
        evidence_type=EvidenceType.PROFILE_ARTIFACT,
        rationale="Synthetic aggregate-only profile evidence.",
        reproducible=reproducible,
    )


def _claim(status: ClaimStatus) -> SemanticClaim:
    return SemanticClaim(
        status=status,
        evidence_tier=(
            EvidenceTier.T3_TEAM_TRIANGULATED_EVIDENCE
            if status is ClaimStatus.CONFIRMED
            else None
        ),
        evidence="Synthetic validation claim.",
    )


def test_concept_can_be_confirmed_while_unit_and_domain_remain_unknown() -> None:
    field = SemanticFieldApproval(
        logical_table_id="PREF02N001",
        source_column="cu_charge_rt",
        semantic_key="pref02.expense_ratio",
        concept=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T3_TEAM_TRIANGULATED_EVIDENCE,
            evidence="Concept triangulated independently of numeric semantics.",
        ),
        unit=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=None,
            evidence="Official unit is not confirmed.",
        ),
        value_domain=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=None,
            evidence="Meaning of zero is not officially confirmed.",
        ),
        operations=(
            OperationApproval(
                operation="EQ",
                status=OperationStatus.CLOSED,
                reason="Unit/domain semantics are not established.",
            ),
        ),
    )

    assert field.concept.status is ClaimStatus.CONFIRMED
    assert field.unit.status is ClaimStatus.NEED_REVIEW
    assert field.value_domain.status is ClaimStatus.NEED_REVIEW
    assert field.open_operations == ()


def test_valid_t4_provenance_allows_one_open_operation() -> None:
    provenance = _provenance()
    field = SemanticFieldApproval(
        logical_table_id="PREF02N001",
        source_column="du_last_aum",
        semantic_key="pref02.aum_latest",
        concept=_claim(ClaimStatus.CONFIRMED),
        unit=_claim(ClaimStatus.NEED_REVIEW),
        value_domain=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence="Observed as unambiguous source-native Decimal values.",
            provenance=(provenance,),
        ),
        operations=(
            OperationApproval(
                operation="SORT_DESC",
                status=OperationStatus.OPEN,
                reason="Source-native ranking needs no unit conversion.",
                evidence="Reproducible Decimal profile.",
                provenance=(provenance,),
            ),
            OperationApproval(
                operation="GE",
                status=OperationStatus.CLOSED,
                reason="Absolute threshold requires confirmed unit/scale.",
            ),
        ),
    )

    assert field.open_operations == ("SORT_DESC",)


def test_profile_artifact_provenance_requires_artifact_path() -> None:
    with pytest.raises(ValueError, match="artifact relative path"):
        _provenance(artifact_path="")


@pytest.mark.parametrize(
    ("table", "column", "message"),
    [
        ("OTHER", "du_last_aum", "source table"),
        ("PREF02N001", "other_column", "source column"),
    ],
)
def test_provenance_identity_must_match_approval(
    table: str,
    column: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SemanticFieldApproval(
            logical_table_id="PREF02N001",
            source_column="du_last_aum",
            semantic_key="pref02.aum_latest",
            concept=_claim(ClaimStatus.CONFIRMED),
            unit=_claim(ClaimStatus.NEED_REVIEW),
            value_domain=SemanticClaim(
                status=ClaimStatus.NEED_REVIEW,
                evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
                evidence="Profile observation only.",
                provenance=(_provenance(table=table, column=column),),
            ),
            operations=(),
        )


def test_t4_confirmed_claim_without_reproducible_artifact_is_rejected() -> None:
    with pytest.raises(ValueError, match="T4 CONFIRMED"):
        SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence="Text alone is insufficient for T4 confirmation.",
        )


def test_open_operation_requires_non_empty_evidence() -> None:
    with pytest.raises(ValueError, match="non-empty evidence"):
        OperationApproval(
            operation="SORT_DESC",
            status=OperationStatus.OPEN,
            reason="Candidate operation.",
            provenance=(_provenance(),),
        )


def test_open_operation_requires_reproducible_artifact_provenance() -> None:
    with pytest.raises(ValueError, match="reproducible artifact provenance"):
        OperationApproval(
            operation="SORT_DESC",
            status=OperationStatus.OPEN,
            reason="Candidate operation.",
            evidence="Text evidence exists.",
            provenance=(_provenance(reproducible=False),),
        )


def test_unknown_concept_cannot_have_open_operation() -> None:
    provenance = _provenance()
    with pytest.raises(ValueError, match="concept UNKNOWN"):
        SemanticFieldApproval(
            logical_table_id="PREF02N001",
            source_column="du_last_aum",
            semantic_key="pref02.aum_latest",
            concept=_claim(ClaimStatus.UNKNOWN),
            unit=_claim(ClaimStatus.NEED_REVIEW),
            value_domain=SemanticClaim(
                status=ClaimStatus.CONFIRMED,
                evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
                evidence="Synthetic validation claim.",
                provenance=(provenance,),
            ),
            operations=(
                OperationApproval(
                    operation="SORT_DESC",
                    status=OperationStatus.OPEN,
                    reason="Candidate operation.",
                    evidence="Synthetic reproducible evidence.",
                    provenance=(provenance,),
                ),
            ),
        )


@pytest.mark.parametrize(
    "value_domain_status",
    [ClaimStatus.UNKNOWN, ClaimStatus.NEED_REVIEW],
)
def test_sort_desc_open_requires_confirmed_value_domain(
    value_domain_status: ClaimStatus,
) -> None:
    provenance = _provenance()
    with pytest.raises(ValueError, match="CONFIRMED value_domain"):
        SemanticFieldApproval(
            logical_table_id="PREF02N001",
            source_column="du_last_aum",
            semantic_key="pref02.aum_latest",
            concept=_claim(ClaimStatus.CONFIRMED),
            unit=_claim(ClaimStatus.NEED_REVIEW),
            value_domain=SemanticClaim(
                status=value_domain_status,
                evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
                evidence="Synthetic validation claim.",
                provenance=(provenance,),
            ),
            operations=(
                OperationApproval(
                    operation="SORT_DESC",
                    status=OperationStatus.OPEN,
                    reason="Candidate operation.",
                    evidence="Synthetic reproducible evidence.",
                    provenance=(provenance,),
                ),
            ),
        )
