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

# 20260824 official-data-migration provenance artifacts (Source of Truth):
#   1. artifacts/profiling/20260824/g1/*  (official schema profile, file
#      manifest, and source-native data profile)
#   2. artifacts/profiling/20260824/g2a/* (typed-rule parse/validation
#      counts)
# These replace all prior artifacts/profiling/g3a1_pref02 and
# artifacts/profiling/g3a1_prbd references.
_G1_SCHEMA_PROFILE_ARTIFACT = "artifacts/profiling/20260824/g1/g1_schema_profile.json"
_G1_FILE_MANIFEST_ARTIFACT = "artifacts/profiling/20260824/g1/g1_file_manifest.json"
_G1_DATA_PROFILE_ARTIFACT = "artifacts/profiling/20260824/g1/g1_data_profile.json"
_G2A_TYPED_RULES_ARTIFACT = "artifacts/profiling/20260824/g2a/g2a_typed_rules.json"

# 20260824 official source-file identity (sha256), confirmed against
# artifacts/profiling/20260824/g1/g1_file_manifest.json.
_PREF02_DATA_SHA256 = (
    "ca6a274aeaf3f884f2f7635d7802558b"
    "c6dabf408871ecb1f71e5a50d9d34067"
)
_PREF02_SCHEMA_SHA256 = (
    "32ac732f0501f4ab518682175fecc507"
    "56ee1eafde9296801f139d62559b5e64"
)
_PRBD_DATA_SHA256 = (
    "574ae5d6c1d98704712c256ed5352cba"
    "ed065ea9c3a6eb7b2a52adb305fa9001"
)
_PRBD_SCHEMA_SHA256 = (
    "9965126695066f9dc07951a78054e9e7"
    "639b6863d1ad2a9616f7e2d8fcadbc4f"
)


def _schema_provenance(
    *,
    logical_table_id: str,
    source_column: str,
    source_identity: str,
    rationale: str,
) -> EvidenceProvenance:
    """Provenance for a claim confirmed directly from the official schema."""

    return EvidenceProvenance(
        evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
        artifact_relative_path=_G1_SCHEMA_PROFILE_ARTIFACT,
        source_logical_table=logical_table_id,
        source_column=source_column,
        source_identity=source_identity,
        evidence_type=EvidenceType.OFFICIAL_SCHEMA,
        rationale=rationale,
        reproducible=True,
    )


def _validation_provenance(
    *,
    logical_table_id: str,
    source_column: str,
    source_identity: str,
    rationale: str,
) -> EvidenceProvenance:
    """Provenance for a claim backed by the 20260824 G2A typed-rule counts."""

    return EvidenceProvenance(
        evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
        artifact_relative_path=_G2A_TYPED_RULES_ARTIFACT,
        source_logical_table=logical_table_id,
        source_column=source_column,
        source_identity=source_identity,
        evidence_type=EvidenceType.INTERNAL_VALIDATION,
        rationale=rationale,
        reproducible=True,
    )


def _profile_provenance(
    *,
    logical_table_id: str,
    source_column: str,
    source_identity: str,
    rationale: str,
) -> EvidenceProvenance:
    """Provenance for a claim backed by the 20260824 G1 source-native profile."""

    return EvidenceProvenance(
        evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
        artifact_relative_path=_G1_DATA_PROFILE_ARTIFACT,
        source_logical_table=logical_table_id,
        source_column=source_column,
        source_identity=source_identity,
        evidence_type=EvidenceType.PROFILE_ARTIFACT,
        rationale=rationale,
        reproducible=True,
    )


def _manifest_provenance(
    *,
    logical_table_id: str,
    source_column: str,
    source_identity: str,
    rationale: str,
) -> EvidenceProvenance:
    """Provenance citing the 20260824 file manifest's hash/immutability record."""

    return EvidenceProvenance(
        evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
        artifact_relative_path=_G1_FILE_MANIFEST_ARTIFACT,
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


_PRBD_FIELD_SPECS = (
    {
        "source_column": "pd_risk_gcd",
        "semantic_key": "prbd.pd_risk_gcd_unresolved",
        "declared_type": "text",
        "official_comment": "상품위험등급 원문 코드",
        "row_count": 21_882,
        "ok_count": 21_882,
        "missing_count": 0,
        "parse_error_count": 0,
        "distinct_count": 7,
    },
    {
        "source_column": "dur",
        "semantic_key": "prbd.dur_unresolved",
        "declared_type": "double precision",
        "official_comment": "듀레이션",
        "row_count": 21_882,
        "ok_count": 21_866,
        "missing_count": 16,
        "parse_error_count": 0,
        "distinct_count": 14_587,
    },
    {
        "source_column": "ndy_dur",
        "semantic_key": "prbd.ndy_dur_unresolved",
        "declared_type": "double precision",
        "official_comment": "익일 듀레이션",
        "row_count": 21_882,
        "ok_count": 21_866,
        "missing_count": 16,
        "parse_error_count": 0,
        "distinct_count": 14_476,
    },
    {
        "source_column": "cov",
        "semantic_key": "prbd.cov_unresolved",
        "declared_type": "double precision",
        "official_comment": "컨벡시티",
        "row_count": 21_882,
        "ok_count": 21_866,
        "missing_count": 16,
        "parse_error_count": 0,
        "distinct_count": 15_801,
    },
)


SEMANTIC_FIELD_APPROVALS: tuple[SemanticFieldApproval, ...] = (
    SemanticFieldApproval(
        logical_table_id="PREF02N001",
        source_column="cu_charge_rt",
        semantic_key="pref02.expense_ratio",
        concept=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
            evidence=(
                "The official PREF02N001 schema declares cu_charge_rt#1 as "
                "numeric(18,6) with comment '연간보수율' (annual expense "
                "rate). T1 confirms the concept only; it does not confirm "
                "unit or scale."
            ),
            provenance=(
                _schema_provenance(
                    logical_table_id="PREF02N001",
                    source_column="cu_charge_rt",
                    source_identity=_PREF02_SCHEMA_SHA256,
                    rationale=(
                        "Official schema column declaration and comment "
                        "identify the expense-ratio concept without "
                        "asserting unit or scale."
                    ),
                ),
            ),
        ),
        unit=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=None,
            evidence=(
                "The official schema does not declare a unit for "
                "cu_charge_rt (declared_unit is null); unit and scale "
                "remain unconfirmed."
            ),
        ),
        value_domain=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence=(
                "The 20260824 G2A typed-rule validation records "
                "6,037/6,037 rows parsed OK with 0 missing and 0 parse "
                "errors across 130 distinct source-native values. This "
                "records parseability and distribution only; it does not "
                "assign a unit, scale, or meaning to zero."
            ),
            provenance=(
                _validation_provenance(
                    logical_table_id="PREF02N001",
                    source_column="cu_charge_rt",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Records parse status and distinct-value "
                        "distribution without assigning a unit, scale, or "
                        "meaning to zero."
                    ),
                ),
                _manifest_provenance(
                    logical_table_id="PREF02N001",
                    source_column="cu_charge_rt",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Confirms the profiled source file's hash and "
                        "immutability for reproducibility."
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
            evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
            evidence=(
                "The official PREF02N001 schema declares du_last_aum#1 as "
                "numeric(28,2) with comment '일간 순자산총액' (daily net "
                "asset value). T1 confirms the concept only; it does not "
                "confirm unit or scale."
            ),
            provenance=(
                _schema_provenance(
                    logical_table_id="PREF02N001",
                    source_column="du_last_aum",
                    source_identity=_PREF02_SCHEMA_SHA256,
                    rationale=(
                        "Official schema column declaration and comment "
                        "identify the latest-AUM concept without asserting "
                        "unit or scale."
                    ),
                ),
            ),
        ),
        unit=SemanticClaim(
            status=ClaimStatus.NEED_REVIEW,
            evidence_tier=None,
            evidence=(
                "The official schema does not declare a unit for "
                "du_last_aum (declared_unit is null); the AUM unit and "
                "scale remain unconfirmed."
            ),
        ),
        value_domain=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence=(
                "The 20260824 G2A typed-rule validation records "
                "5,832/6,037 rows parsed OK as finite Decimal-parseable "
                "source strings, 205 missing values, 0 parse errors, and "
                "4,899 distinct source-native values, supporting exact "
                "Decimal ordering."
            ),
            provenance=(
                _validation_provenance(
                    logical_table_id="PREF02N001",
                    source_column="du_last_aum",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Reproduces complete finite Decimal parsing and "
                        "exact source-native ordering with explicit null "
                        "handling."
                    ),
                ),
                _manifest_provenance(
                    logical_table_id="PREF02N001",
                    source_column="du_last_aum",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Confirms the profiled source file's hash and "
                        "immutability for reproducibility."
                    ),
                ),
            ),
        ),
        operations=(
            OperationApproval(
                operation="PROJECT",
                status=OperationStatus.OPEN,
                reason=(
                    "The source-native metric may be returned with its raw "
                    "lineage; projection does not authorize a unit "
                    "conversion."
                ),
                evidence=(
                    "The 20260824 G2A typed-rule validation reproduces "
                    "Decimal parsing and null handling for du_last_aum#1."
                ),
                provenance=(
                    _validation_provenance(
                        logical_table_id="PREF02N001",
                        source_column="du_last_aum",
                        source_identity=_PREF02_DATA_SHA256,
                        rationale=(
                            "Supports returning the unconverted "
                            "source-native AUM value with raw source "
                            "lineage."
                        ),
                    ),
                ),
            ),
            OperationApproval(
                operation="SORT_DESC",
                status=OperationStatus.OPEN,
                reason=(
                    "SORT_DESC is source-native Decimal ranking and does "
                    "not mean a unit conversion; missing values sort last "
                    "and source_row_id breaks ties."
                ),
                evidence=(
                    "artifacts/profiling/20260824/g2a/g2a_typed_rules.json "
                    "PREF02N001.du_last_aum#1; app/structured/compiler.py "
                    "orders DESC NULLS LAST then source_row_id ASC."
                ),
                provenance=(
                    _validation_provenance(
                        logical_table_id="PREF02N001",
                        source_column="du_last_aum",
                        source_identity=_PREF02_DATA_SHA256,
                        rationale=(
                            "Supports unit-free source-native descending "
                            "rank; absolute thresholds remain outside "
                            "approval."
                        ),
                    ),
                ),
            ),
            *_closed_operations(
                ("LT", "LE", "GT", "GE"),
                reason=(
                    "Absolute threshold comparison requires an approved "
                    "AUM unit and scale."
                ),
            ),
        ),
        notes=(
            "SORT_DESC is OPEN from reproducible source-native validation; "
            "absolute thresholds remain closed until unit approval."
        ),
    ),
    SemanticFieldApproval(
        logical_table_id="PREF02N001",
        source_column="pd_itm_no",
        semantic_key="pref02.product_identifier",
        concept=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
            evidence=(
                "The official PREF02N001 schema declares pd_itm_no#1 as "
                "text with comment '해외 ETF RIC'. T1 confirms the "
                "identifier concept only; the official schema declares no "
                "primary key for this table."
            ),
            provenance=(
                _schema_provenance(
                    logical_table_id="PREF02N001",
                    source_column="pd_itm_no",
                    source_identity=_PREF02_SCHEMA_SHA256,
                    rationale=(
                        "Official schema column declaration and comment "
                        "identify the RIC identifier concept; the schema's "
                        "declared_primary_key_columns is empty, so no "
                        "official primary key is declared."
                    ),
                ),
            ),
        ),
        unit=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
            evidence=(
                "The official schema declares pd_itm_no as text; an "
                "opaque identifier is not a measured value."
            ),
        ),
        value_domain=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence=(
                "The 20260824 G2A typed-rule validation records "
                "6,037/6,037 rows present with 0 missing and 6,037 "
                "distinct source-native identifier strings. The 20260824 "
                "G1 data profile independently records pd_itm_no#1 as a "
                "candidate identifier with 0 duplicate values among 6,037 "
                "non-null observations. This is a statistically observed "
                "unique candidate, not an official primary key."
            ),
            provenance=(
                _validation_provenance(
                    logical_table_id="PREF02N001",
                    source_column="pd_itm_no",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Reproduces completeness and distinct-value counts "
                        "for the identifier column without interpreting "
                        "its code."
                    ),
                ),
                _profile_provenance(
                    logical_table_id="PREF02N001",
                    source_column="pd_itm_no",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Reproduces the candidate-identifier structural "
                        "evaluation (0 duplicates among 6,037 non-null "
                        "values), supporting statistical uniqueness only, "
                        "not an official primary-key declaration."
                    ),
                ),
            ),
        ),
        operations=(
            OperationApproval(
                operation="PROJECT",
                status=OperationStatus.OPEN,
                reason=(
                    "The statistically unique source-native identifier "
                    "may identify a returned row; no filter or sort "
                    "permission is implied."
                ),
                evidence=(
                    "The 20260824 G1 data profile and G2A typed-rule "
                    "validation together establish a stable, statistically "
                    "unique source-native identifier across 6,037 rows."
                ),
                provenance=(
                    _validation_provenance(
                        logical_table_id="PREF02N001",
                        source_column="pd_itm_no",
                        source_identity=_PREF02_DATA_SHA256,
                        rationale="Supports projection and row identification only.",
                    ),
                ),
            ),
            *_closed_operations(
                ("EQ", "NE", "LT", "LE", "GT", "GE", "SORT_ASC", "SORT_DESC"),
                reason="Only projection is approved for this G3 field.",
            ),
        ),
        notes=(
            "Projection-only approval; pd_itm_no is a statistical unique "
            "candidate observed in the 20260824 G1 profile, not a "
            "declared official primary key."
        ),
    ),
    SemanticFieldApproval(
        logical_table_id="PREF02N001",
        source_column="pd_nm",
        semantic_key="pref02.product_name",
        concept=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
            evidence=(
                "The official PREF02N001 schema declares pd_nm#1 as text "
                "with comment '상품명' (product name)."
            ),
            provenance=(
                _schema_provenance(
                    logical_table_id="PREF02N001",
                    source_column="pd_nm",
                    source_identity=_PREF02_SCHEMA_SHA256,
                    rationale=(
                        "Official schema column declaration and comment "
                        "identify the product display-name concept."
                    ),
                ),
            ),
        ),
        unit=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
            evidence=(
                "The official schema declares pd_nm as text; a product "
                "display name is not a measured value."
            ),
        ),
        value_domain=SemanticClaim(
            status=ClaimStatus.CONFIRMED,
            evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
            evidence=(
                "The 20260824 G2A typed-rule validation records "
                "6,037/6,037 rows present with 0 missing and 6,009 "
                "distinct source-native text values; names are not "
                "treated as a unique identifier."
            ),
            provenance=(
                _validation_provenance(
                    logical_table_id="PREF02N001",
                    source_column="pd_nm",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Reproduces display-text completeness without "
                        "asserting that names are unique identifiers."
                    ),
                ),
                _manifest_provenance(
                    logical_table_id="PREF02N001",
                    source_column="pd_nm",
                    source_identity=_PREF02_DATA_SHA256,
                    rationale=(
                        "Confirms the profiled source file's hash and "
                        "immutability for reproducibility."
                    ),
                ),
            ),
        ),
        operations=(
            OperationApproval(
                operation="PROJECT",
                status=OperationStatus.OPEN,
                reason=(
                    "The source-native name may be displayed with row "
                    "lineage; no filter or sort permission is implied."
                ),
                evidence=(
                    "Official schema meaning and the 20260824 G2A "
                    "text-completeness validation support display-only "
                    "projection."
                ),
                provenance=(
                    _validation_provenance(
                        logical_table_id="PREF02N001",
                        source_column="pd_nm",
                        source_identity=_PREF02_DATA_SHA256,
                        rationale="Supports source-native display projection only.",
                    ),
                ),
            ),
            *_closed_operations(
                ("EQ", "NE", "LT", "LE", "GT", "GE", "SORT_ASC", "SORT_DESC"),
                reason="Only projection is approved for this G3 field.",
            ),
        ),
        notes="Projection-only approval; names are not treated as unique.",
    ),
    *(
        SemanticFieldApproval(
            logical_table_id="PRBD01N001",
            source_column=spec["source_column"],
            semantic_key=spec["semantic_key"],
            concept=SemanticClaim(
                status=ClaimStatus.CONFIRMED,
                evidence_tier=EvidenceTier.T1_OFFICIAL_SCHEMA,
                evidence=(
                    f"The official PRBD01N001 schema declares "
                    f"{spec['source_column']}#1 as {spec['declared_type']} "
                    f"with comment '{spec['official_comment']}'. T1 "
                    "confirms only the schema-declared name and type; it "
                    "does not interpret any coded value's meaning or "
                    "approve a unit."
                ),
                provenance=(
                    _schema_provenance(
                        logical_table_id="PRBD01N001",
                        source_column=spec["source_column"],
                        source_identity=_PRBD_SCHEMA_SHA256,
                        rationale=(
                            "Official schema column declaration and "
                            "comment identify the field name and type "
                            "without interpreting coded values or "
                            "approving a unit."
                        ),
                    ),
                ),
            ),
            unit=SemanticClaim(
                status=ClaimStatus.NEED_REVIEW,
                evidence_tier=None,
                evidence=(
                    f"The official schema does not declare a unit for "
                    f"{spec['source_column']} (declared_unit is null); "
                    "unit and scale remain unconfirmed."
                ),
            ),
            value_domain=SemanticClaim(
                status=ClaimStatus.NEED_REVIEW,
                evidence_tier=EvidenceTier.T4_INTERNAL_REPRODUCIBLE_VALIDATION,
                evidence=(
                    "The 20260824 G2A typed-rule validation records "
                    f"{spec['row_count']:,}/{spec['row_count']:,} rows "
                    f"with {spec['ok_count']:,} parsed OK, "
                    f"{spec['missing_count']:,} missing, "
                    f"{spec['parse_error_count']:,} parse errors, and "
                    f"{spec['distinct_count']:,} distinct source-native "
                    "values. This records source-native distribution only "
                    "and does not approve financial meaning."
                ),
                provenance=(
                    _validation_provenance(
                        logical_table_id="PRBD01N001",
                        source_column=spec["source_column"],
                        source_identity=_PRBD_DATA_SHA256,
                        rationale=(
                            "Records row/missing/distinct and parseability "
                            "from the 20260824 typed-rule validation "
                            "without semantic inference."
                        ),
                    ),
                    _manifest_provenance(
                        logical_table_id="PRBD01N001",
                        source_column=spec["source_column"],
                        source_identity=_PRBD_DATA_SHA256,
                        rationale=(
                            "Confirms the profiled source file's hash and "
                            "immutability for reproducibility."
                        ),
                    ),
                ),
            ),
            operations=_closed_operations(
                _RUNTIME_NUMERIC_OPERATIONS,
                reason=(
                    "Runtime operations remain closed until unit, scale, "
                    "and (for coded columns) code-value meaning are "
                    "officially approved; a T1-confirmed schema concept "
                    "alone does not open numeric or coded operations."
                ),
            ),
            notes=(
                "semantic_key retains its legacy '_unresolved' suffix from "
                "prior UNKNOWN-concept naming; concept is now "
                "T1_OFFICIAL_SCHEMA CONFIRMED but unit, scale, and (for "
                "coded columns) code-value meaning remain unresolved, so "
                "the key is kept unchanged to avoid a runtime rename risk. "
                "T1 schema confirmation establishes the field's declared "
                "name and type only; it does not establish financial "
                "interpretation."
            ),
        )
        for spec in _PRBD_FIELD_SPECS
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

_DEFAULT_PROJECTIONS = MappingProxyType(
    {
        ("PREF02N001", "pref02.aum_latest"): (
            "pref02.product_identifier",
            "pref02.product_name",
            "pref02.aum_latest",
        ),
    }
)

_PRODUCT_IDENTIFIER_KEYS = MappingProxyType(
    {"PREF02N001": "pref02.product_identifier"}
)


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


def get_default_projection_keys(
    logical_table_id: str,
    requested_semantic_key: str,
) -> tuple[str, ...]:
    """Return explicitly approved display projections for one query metric."""

    return _DEFAULT_PROJECTIONS.get(
        (logical_table_id, requested_semantic_key),
        (requested_semantic_key,),
    )


def get_product_identifier_key(logical_table_id: str) -> str | None:
    """Return an explicitly approved row-level business identifier key."""

    return _PRODUCT_IDENTIFIER_KEYS.get(logical_table_id)


__all__ = [
    "SEMANTIC_FIELD_APPROVALS",
    "get_semantic_field_approval",
    "get_default_projection_keys",
    "get_product_identifier_key",
    "get_table_semantic_approvals",
    "validate_semantic_registry",
]
