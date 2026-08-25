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


_CURRENT_ARTIFACT_PREFIX = "artifacts/profiling/20260824/"

_OLD_SHA256_FRAGMENTS = (
    "3cec19043f742771e0016d56fe806f19ad78f4295d1ae59192740a78feb2253b",
    "728f44a567a986d21cf843d711c6c4dfa1a24d05b39c7da0541b981b57ecccf8",
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
    assert approval.concept.evidence_tier is EvidenceTier.T1_OFFICIAL_SCHEMA
    assert approval.unit.status is ClaimStatus.NEED_REVIEW
    assert approval.value_domain.status is ClaimStatus.NEED_REVIEW
    assert (
        approval.value_domain.provenance[0].evidence_type
        is EvidenceType.INTERNAL_VALIDATION
    )
    assert approval.open_operations == ()
    assert set(_operation_statuses("PREF02N001", "pref02.expense_ratio").values()) == {
        OperationStatus.CLOSED
    }


def test_aum_has_valid_t4_provenance_and_only_source_native_sort_open() -> None:
    approval = get_semantic_field_approval("PREF02N001", "pref02.aum_latest")

    assert approval is not None
    assert approval.concept.evidence_tier is EvidenceTier.T1_OFFICIAL_SCHEMA
    assert approval.value_domain.status is ClaimStatus.CONFIRMED
    assert (
        approval.value_domain.evidence_tier
        is EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION
    )
    provenance = approval.value_domain.provenance[0]
    assert provenance.artifact_relative_path == (
        "artifacts/profiling/20260824/g2a/g2a_typed_rules.json"
    )
    assert provenance.source_identity == (
        "ca6a274aeaf3f884f2f7635d7802558b"
        "c6dabf408871ecb1f71e5a50d9d34067"
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
        "pd_risk_gcd",
        "dur",
        "ndy_dur",
        "cov",
    )
    assert get_table_semantic_approvals("PREF01N001") == ()
    assert get_semantic_field_approval("PREF01N001", "pref02.expense_ratio") is None


def test_unknown_semantic_key_fails_closed() -> None:
    assert get_semantic_field_approval("PREF02N001", "pref02.unknown") is None


@pytest.mark.parametrize(
    ("semantic_key", "source_column"),
    (
        ("pref02.product_identifier", "pd_itm_no"),
        ("pref02.product_name", "pd_nm"),
    ),
)
def test_pref02_display_fields_are_projection_only(
    semantic_key: str,
    source_column: str,
) -> None:
    approval = get_semantic_field_approval("PREF02N001", semantic_key)

    assert approval is not None
    assert approval.source_column == source_column
    assert approval.concept.status is ClaimStatus.CONFIRMED
    assert approval.concept.evidence_tier is EvidenceTier.T1_OFFICIAL_SCHEMA
    assert approval.open_operations == ("PROJECT",)
    assert approval.value_domain.provenance[0].is_reproducible_artifact is True
    assert all(
        operation.status is OperationStatus.CLOSED
        for operation in approval.operations
        if operation.operation != "PROJECT"
    )


def test_pd_itm_no_is_statistical_unique_candidate_not_official_pk() -> None:
    approval = get_semantic_field_approval(
        "PREF02N001", "pref02.product_identifier"
    )

    assert approval is not None
    assert "no primary key" in approval.concept.evidence.lower()
    assert "not an official primary key" in approval.value_domain.evidence.lower()
    assert "not a declared official primary key" in approval.notes.lower()
    assert "statistical unique candidate" in approval.notes.lower()


def test_pd_nm_is_not_treated_as_unique_identifier() -> None:
    approval = get_semantic_field_approval("PREF02N001", "pref02.product_name")

    assert approval is not None
    assert "not treated as unique" in approval.notes.lower()


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
def test_prbd_concept_confirmed_but_operations_remain_closed(
    semantic_key: str,
) -> None:
    """PRBD concept is T1-confirmed from the official schema, but unit,
    scale, and code-value meaning remain unapproved, so no operation opens.
    """

    approval = get_semantic_field_approval("PRBD01N001", semantic_key)

    assert approval is not None
    assert approval.concept.status is ClaimStatus.CONFIRMED
    assert approval.concept.evidence_tier is EvidenceTier.T1_OFFICIAL_SCHEMA
    assert approval.unit.status is ClaimStatus.NEED_REVIEW
    assert approval.value_domain.status is ClaimStatus.NEED_REVIEW
    provenance = approval.value_domain.provenance[0]
    assert provenance.artifact_relative_path == (
        "artifacts/profiling/20260824/g2a/g2a_typed_rules.json"
    )
    assert provenance.source_column == approval.source_column
    assert provenance.source_identity == (
        "574ae5d6c1d98704712c256ed5352cba"
        "ed065ea9c3a6eb7b2a52adb305fa9001"
    )
    assert provenance.is_reproducible_artifact is True
    assert approval.open_operations == ()
    assert all(
        operation.status is OperationStatus.CLOSED
        for operation in approval.operations
    )


def test_prbd_source_columns_use_lowercase_current_physical_identity() -> None:
    prbd = get_table_semantic_approvals("PRBD01N001")

    assert {approval.source_column for approval in prbd} == {
        "pd_risk_gcd",
        "dur",
        "ndy_dur",
        "cov",
    }
    for approval in prbd:
        assert approval.source_column == approval.source_column.lower()
        assert approval.qualified_name == f"{approval.source_column}#1"


def test_registry_provenance_uses_current_20260824_artifacts_only() -> None:
    for approval in (
        *get_table_semantic_approvals("PREF02N001"),
        *get_table_semantic_approvals("PRBD01N001"),
    ):
        claims = (approval.concept, approval.unit, approval.value_domain)
        provenance_items = [
            item for claim in claims for item in claim.provenance
        ]
        provenance_items += [
            item
            for operation in approval.operations
            for item in operation.provenance
        ]
        assert provenance_items, f"no provenance recorded for {approval.source_column}"
        for item in provenance_items:
            assert item.artifact_relative_path.startswith(
                _CURRENT_ARTIFACT_PREFIX
            )
            assert "g3a1" not in item.artifact_relative_path
            assert item.source_identity not in _OLD_SHA256_FRAGMENTS
