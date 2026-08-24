from dataclasses import replace

import pytest

from mappings.semantic.models import (
    ClaimStatus,
    EvidenceTier,
    EvidenceType,
    OperationStatus,
)
from mappings.semantic.registry import (
    get_semantic_field_approval,
    get_table_semantic_approvals,
    validate_semantic_registry,
)


def _operation_statuses(
    logical_table_id: str,
    semantic_key: str,
) -> dict[str, OperationStatus]:
    approval = get_semantic_field_approval(logical_table_id, semantic_key)
    assert approval is not None
    return {item.operation: item.status for item in approval.operations}


def test_expense_ratio_profile_does_not_promote_numeric_semantics() -> None:
    approval = get_semantic_field_approval(
        "PREF02N001", "pref02.expense_ratio"
    )

    assert approval is not None
    assert approval.concept.status is ClaimStatus.CONFIRMED
    assert approval.unit.status is ClaimStatus.NEED_REVIEW
    assert approval.value_domain.status is ClaimStatus.NEED_REVIEW
    assert (
        approval.value_domain.provenance[0].evidence_type
        is EvidenceType.PROFILE_ARTIFACT
    )
    assert approval.open_operations == ()
    assert set(_operation_statuses("PREF02N001", "pref02.expense_ratio").values()) == {
        OperationStatus.CLOSED
    }


def test_aum_has_valid_t4_provenance_and_only_source_native_sort_open() -> None:
    approval = get_semantic_field_approval("PREF02N001", "pref02.aum_latest")

    assert approval is not None
    assert approval.value_domain.status is ClaimStatus.CONFIRMED
    assert (
        approval.value_domain.evidence_tier
        is EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION
    )
    provenance = approval.value_domain.provenance[0]
    assert provenance.artifact_relative_path == (
        "artifacts/profiling/g3a1_pref02/g1_data_profile.json"
    )
    assert provenance.source_identity == (
        "3cec19043f742771e0016d56fe806f19"
        "ad78f4295d1ae59192740a78feb2253b"
    )
    assert provenance.is_reproducible_artifact is True
    assert approval.open_operations == ("PROJECT", "SORT_DESC")
    assert _operation_statuses("PREF02N001", "pref02.aum_latest") == {
        "PROJECT": OperationStatus.OPEN,
        "SORT_DESC": OperationStatus.OPEN,
        "LT": OperationStatus.CLOSED,
        "LE": OperationStatus.CLOSED,
        "GT": OperationStatus.CLOSED,
        "GE": OperationStatus.CLOSED,
    }


def test_lookup_is_table_scoped() -> None:
    pref02 = get_table_semantic_approvals("PREF02N001")
    prbd = get_table_semantic_approvals("PRBD01N001")

    assert tuple(approval.source_column for approval in pref02) == (
        "cu_charge_rt",
        "du_last_aum",
        "pd_itm_no",
        "pd_nm",
    )
    assert tuple(approval.source_column for approval in prbd) == (
        "PD_RISK_GCD",
        "DUR",
        "NDY_DUR",
        "COV",
    )
    assert get_table_semantic_approvals("PREF01N001") == ()
    assert get_semantic_field_approval("PREF01N001", "pref02.expense_ratio") is None


def test_unknown_semantic_key_fails_closed() -> None:
    assert get_semantic_field_approval("PREF02N001", "pref02.unknown") is None


@pytest.mark.parametrize(
    ("semantic_key", "source_column", "tier"),
    (
        (
            "pref02.product_identifier",
            "pd_itm_no",
            EvidenceTier.T3_TEAM_TRIANGULATED_EVIDENCE,
        ),
        (
            "pref02.product_name",
            "pd_nm",
            EvidenceTier.T2_OFFICIAL_SIBLING_SCHEMA,
        ),
    ),
)
def test_pref02_display_fields_are_projection_only(
    semantic_key: str,
    source_column: str,
    tier: EvidenceTier,
) -> None:
    approval = get_semantic_field_approval("PREF02N001", semantic_key)

    assert approval is not None
    assert approval.source_column == source_column
    assert approval.concept.status is ClaimStatus.CONFIRMED
    assert approval.concept.evidence_tier is tier
    assert approval.open_operations == ("PROJECT",)
    assert approval.value_domain.provenance[0].is_reproducible_artifact is True
    assert all(
        operation.status is OperationStatus.CLOSED
        for operation in approval.operations
        if operation.operation != "PROJECT"
    )


def test_duplicate_source_identity_within_table_is_rejected() -> None:
    approval = get_semantic_field_approval("PREF02N001", "pref02.aum_latest")
    assert approval is not None
    duplicate = replace(approval, semantic_key="pref02.aum_duplicate")

    with pytest.raises(ValueError, match="duplicate source identities"):
        validate_semantic_registry((approval, duplicate))


@pytest.mark.parametrize(
    "semantic_key",
    [
        "prbd.pd_risk_gcd_unresolved",
        "prbd.dur_unresolved",
        "prbd.ndy_dur_unresolved",
        "prbd.cov_unresolved",
    ],
)
def test_prbd_unresolved_concepts_remain_closed(semantic_key: str) -> None:
    approval = get_semantic_field_approval("PRBD01N001", semantic_key)

    assert approval is not None
    assert approval.concept.status is ClaimStatus.UNKNOWN
    assert approval.value_domain.status is ClaimStatus.NEED_REVIEW
    provenance = approval.value_domain.provenance[0]
    assert provenance.artifact_relative_path == (
        "artifacts/profiling/g3a1_prbd/g1_data_profile.json"
    )
    assert provenance.source_column == approval.source_column
    assert provenance.source_identity == (
        "728f44a567a986d21cf843d711c6c4d"
        "fa1a24d05b39c7da0541b981b57ecccf8"
    )
    assert provenance.is_reproducible_artifact is True
    assert approval.open_operations == ()
    assert all(
        operation.status is OperationStatus.CLOSED
        for operation in approval.operations
    )
