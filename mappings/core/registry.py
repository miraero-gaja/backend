"""Minimal, officially evidenced field allowlist for G2 Core QA.

This registry is deliberately narrower than the 207-column typed staging
schema.  A column is present here only after a field-level review of the
official schema description.  Columns that are absent remain ``UNMAPPED`` for
agent use even though they may still be stored in PostgreSQL.

Semantic keys are table-scoped on purpose.  G2 does not claim that similarly
named fields across product families are one canonical concept.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class SemanticStatus(StrEnum):
    """Approval state for agent-visible semantic field selection."""

    CONFIRMED = "CONFIRMED"
    NEED_REVIEW = "NEED_REVIEW"
    UNMAPPED = "UNMAPPED"


class CoreUnitStatus(StrEnum):
    """Whether official evidence establishes the field's measurement unit."""

    CONFIRMED = "CONFIRMED"
    NEED_REVIEW = "NEED_REVIEW"
    UNMAPPED = "UNMAPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


ALLOWED_OPERATIONS = frozenset({"EQ", "NE", "LT", "LE", "GT", "GE", "SORT"})
SUPPORTED_TARGET_TYPES = frozenset({"TEXT", "DECIMAL", "INTEGER", "DATE", "TIMESTAMP"})
OFFICIAL_TABLE_COLUMN_COUNTS: Mapping[str, int] = MappingProxyType(
    {
        "PRBD01N001": 40,
        "PREF01N001": 73,
        "PREF02N001": 49,
        "PRFD01N001": 45,
    }
)
OFFICIAL_COLUMN_COUNT = sum(OFFICIAL_TABLE_COLUMN_COUNTS.values())

_SEMANTIC_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True, slots=True)
class CoreFieldMapping:
    """One reviewed source field and its deterministic query permissions."""

    semantic_field_key: str
    logical_table_id: str
    source_column: str
    qualified_name: str
    official_schema_description: str
    target_type: str
    allowed_operations: tuple[str, ...]
    semantic_status: SemanticStatus
    unit_status: CoreUnitStatus
    notes: str

    def __post_init__(self) -> None:
        if not _SEMANTIC_KEY_PATTERN.fullmatch(self.semantic_field_key):
            raise ValueError(
                "semantic_field_key must be a stable, table-scoped dotted key"
            )
        if self.logical_table_id not in OFFICIAL_TABLE_COLUMN_COUNTS:
            raise ValueError(f"unknown logical_table_id: {self.logical_table_id}")
        if not self.source_column:
            raise ValueError("source_column must not be empty")
        if self.qualified_name != f"{self.source_column}#1":
            raise ValueError("qualified_name must preserve the official #1 occurrence")
        if not self.official_schema_description.strip():
            raise ValueError("official_schema_description must not be blank")
        if self.target_type not in SUPPORTED_TARGET_TYPES:
            raise ValueError(f"unsupported target_type: {self.target_type}")
        if len(set(self.allowed_operations)) != len(self.allowed_operations):
            raise ValueError("allowed_operations must not contain duplicates")
        invalid_operations = set(self.allowed_operations) - ALLOWED_OPERATIONS
        if invalid_operations:
            raise ValueError(
                f"unsupported allowed_operations: {sorted(invalid_operations)}"
            )
        if self.semantic_status is not SemanticStatus.CONFIRMED and self.allowed_operations:
            raise ValueError("only CONFIRMED fields may expose query operations")
        if self.semantic_status is SemanticStatus.CONFIRMED and not self.allowed_operations:
            raise ValueError("CONFIRMED fields must expose at least one safe operation")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready record without changing the reviewed values."""

        record = asdict(self)
        record["semantic_status"] = self.semantic_status.value
        record["unit_status"] = self.unit_status.value
        record["allowed_operations"] = list(self.allowed_operations)
        return record


def _field(
    semantic_field_key: str,
    logical_table_id: str,
    source_column: str,
    official_schema_description: str,
    target_type: str,
    allowed_operations: tuple[str, ...],
    semantic_status: SemanticStatus,
    unit_status: CoreUnitStatus,
    notes: str,
) -> CoreFieldMapping:
    return CoreFieldMapping(
        semantic_field_key=semantic_field_key,
        logical_table_id=logical_table_id,
        source_column=source_column,
        qualified_name=f"{source_column}#1",
        official_schema_description=official_schema_description,
        target_type=target_type,
        allowed_operations=allowed_operations,
        semantic_status=semantic_status,
        unit_status=unit_status,
        notes=notes,
    )


_TEXT_EQ = ("EQ", "NE")
_ORDER_ONLY = ("SORT",)
_NUMERIC_RANGE = ("EQ", "NE", "LT", "LE", "GT", "GE", "SORT")
_TEMPORAL_RANGE = ("EQ", "NE", "LT", "LE", "GT", "GE", "SORT")

_OFFICIAL_DESCRIPTION_NOTE = (
    "Meaning is taken verbatim from the official schema display name; no alias "
    "or cross-product canonical merge is asserted."
)
_SOURCE_NATIVE_ORDER_NOTE = (
    "Official description confirms the metric, but no official unit/scale is "
    "declared. Only source-native ordering is allowed; no conversion or "
    "threshold interpretation is performed."
)


CORE_FIELD_MAPPINGS: tuple[CoreFieldMapping, ...] = (
    # PREF01N001 (domestic ETF): identifiers, names, market/category, and risk.
    _field(
        "pref01.product_name",
        "PREF01N001",
        "pd_nm",
        "상품명",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.product_code",
        "PREF01N001",
        "pd_itm_no",
        "상품번호",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.mirae_product_code",
        "PREF01N001",
        "pd_itm_no_ma",
        "상품번호_미래에셋",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.product_group",
        "PREF01N001",
        "pd_grp_no",
        "상품군종류",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.exchange_code",
        "PREF01N001",
        "pd_exg_mkt_cd",
        "거래소코드",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.exchange_name",
        "PREF01N001",
        "pd_exg_mkt_nm",
        "거래소명",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.market_code",
        "PREF01N001",
        "pd_mkt_id",
        "상품거래시장코드",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.market_name",
        "PREF01N001",
        "pd_mkt_nm",
        "상품거래시장",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.investment_asset_type",
        "PREF01N001",
        "wu_inv_ast_type",
        "투자자산군",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.investment_region",
        "PREF01N001",
        "wu_inv_rgn",
        "투자지역",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.risk_grade_code",
        "PREF01N001",
        "pd_risk_cd",
        "상품등급코드",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.risk_grade_name",
        "PREF01N001",
        "pd_risk_nm",
        "상품등급명",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.sale_available",
        "PREF01N001",
        "pd_sale_yn",
        "상품판매여부",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "pref01.trading_suspended",
        "PREF01N001",
        "pd_tr_yn",
        "상품거래정지혀부",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        "The official display-name typo is preserved verbatim; code values are not reinterpreted.",
    ),
    _field(
        "pref01.listed_share_count",
        "PREF01N001",
        "pd_lst_stk_cnt",
        "상품상장주식수",
        "DECIMAL",
        _NUMERIC_RANGE,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        "The official description explicitly identifies a share count and the schema declares numeric. Comparisons use the unconverted source-native value; no scale is inferred.",
    ),
    _field(
        "pref01.daily_updated_at",
        "PREF01N001",
        "du_upt_dt",
        "일간갱신일자",
        "TIMESTAMP",
        _TEMPORAL_RANGE,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        "Official description and declared timestamp type both support temporal comparison and ordering.",
    ),
    _field(
        "pref01.return_1m",
        "PREF01N001",
        "du_er_1m",
        "수익률_1M",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
    _field(
        "pref01.return_3m",
        "PREF01N001",
        "du_er_3m",
        "수익률_3M",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
    _field(
        "pref01.return_1y",
        "PREF01N001",
        "du_er_1y",
        "수익률_1Y",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
    _field(
        "pref01.aum_latest",
        "PREF01N001",
        "du_last_aum",
        "최종AUM",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
    # Clear business labels whose current technical type/unit is not query-safe.
    _field(
        "pref01.total_fee_rate",
        "PREF01N001",
        "cu_charge_rt",
        "총보수요율",
        "TEXT",
        (),
        SemanticStatus.NEED_REVIEW,
        CoreUnitStatus.UNMAPPED,
        "Meaning is explicit, but the official type is text and no rate scale is declared; numeric querying is blocked.",
    ),
    _field(
        "pref01.other_expense_rate",
        "PREF01N001",
        "cu_charge_etc_rt",
        "기타비용요율",
        "TEXT",
        (),
        SemanticStatus.NEED_REVIEW,
        CoreUnitStatus.UNMAPPED,
        "Meaning is explicit, but the official type is text and no rate scale is declared; numeric querying is blocked.",
    ),
    _field(
        "pref01.trading_available_date",
        "PREF01N001",
        "pd_lstg_dt",
        "상품거래가능일자",
        "TEXT",
        (),
        SemanticStatus.NEED_REVIEW,
        CoreUnitStatus.NOT_APPLICABLE,
        "The official description is date-like, but the declared/typed target is text; temporal operations are blocked.",
    ),
    _field(
        "pref01.trading_end_date",
        "PREF01N001",
        "pd_lste_dt",
        "상품거래종료일자",
        "TEXT",
        (),
        SemanticStatus.NEED_REVIEW,
        CoreUnitStatus.NOT_APPLICABLE,
        "The official description is date-like, but the declared/typed target is text; temporal operations are blocked.",
    ),
    # PRFD01N001 (public fund): identifiers, categories, risk, size, returns.
    _field(
        "prfd.product_name",
        "PRFD01N001",
        "itm_nm",
        "종목명",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.product_code",
        "PRFD01N001",
        "itm_no",
        "종목번호",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.investment_region",
        "PRFD01N001",
        "fd_ivst_rgn_desc",
        "펀드투자지역구분코드 설명",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.setting_type_code",
        "PRFD01N001",
        "fd_set_pcd",
        "펀드설정유형코드",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        "Field meaning is explicit; code values remain opaque and require exact-value filtering.",
    ),
    _field(
        "prfd.public_private_category",
        "PRFD01N001",
        "prvo_pbff_desc",
        "사모/공모구분코드 설명",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.sale_available",
        "PRFD01N001",
        "sale_yn",
        "판매여부",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.mirae_sale_available",
        "PRFD01N001",
        "thco_sale_yn",
        "당사판매여부",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.currency_code",
        "PRFD01N001",
        "curr_cd",
        "통화코드",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        "The field is the currency code itself; this does not establish units for separate amount fields.",
    ),
    _field(
        "prfd.risk_grade_code",
        "PRFD01N001",
        "zrin_fd_ivst_risk_gcd",
        "제로인펀드투자위험등급코드",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.risk_grade_name",
        "PRFD01N001",
        "zrin_fd_ivst_risk_grd_nm",
        "제로인펀드투자위험등급명",
        "TEXT",
        _TEXT_EQ,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.NOT_APPLICABLE,
        _OFFICIAL_DESCRIPTION_NOTE,
    ),
    _field(
        "prfd.net_assets",
        "PRFD01N001",
        "fd_nast_suma",
        "펀드 순자산",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
    _field(
        "prfd.return_1m",
        "PRFD01N001",
        "fd_mm1_ern_r",
        "펀드 1개월수익률",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
    _field(
        "prfd.return_3m",
        "PRFD01N001",
        "fd_mm3_ern_r",
        "펀드 3개월수익률",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
    _field(
        "prfd.return_1y",
        "PRFD01N001",
        "fd_yr1_ern_r",
        "펀드 1년수익률",
        "DECIMAL",
        _ORDER_ONLY,
        SemanticStatus.CONFIRMED,
        CoreUnitStatus.UNMAPPED,
        _SOURCE_NATIVE_ORDER_NOTE,
    ),
)


def validate_core_field_registry(
    entries: Iterable[CoreFieldMapping] = CORE_FIELD_MAPPINGS,
) -> dict[str, Any]:
    """Validate unique identities and the strict confirmed-only allowlist."""

    records = tuple(entries)
    keys = [entry.semantic_field_key for entry in records]
    source_identities = [
        (entry.logical_table_id, entry.qualified_name) for entry in records
    ]
    duplicate_keys = sorted(key for key, count in Counter(keys).items() if count > 1)
    duplicate_sources = sorted(
        f"{table_id}.{qualified_name}"
        for (table_id, qualified_name), count in Counter(source_identities).items()
        if count > 1
    )
    unsafe_non_confirmed = sorted(
        entry.semantic_field_key
        for entry in records
        if entry.semantic_status is not SemanticStatus.CONFIRMED
        and entry.allowed_operations
    )
    is_valid = (
        not duplicate_keys
        and not duplicate_sources
        and not unsafe_non_confirmed
        and len(records) <= OFFICIAL_COLUMN_COUNT
    )
    return {
        "registry_entry_count": len(records),
        "official_column_count": OFFICIAL_COLUMN_COUNT,
        "is_minimal_subset": len(records) < OFFICIAL_COLUMN_COUNT,
        "duplicate_semantic_field_keys": duplicate_keys,
        "duplicate_source_identities": duplicate_sources,
        "non_confirmed_with_operations": unsafe_non_confirmed,
        "is_valid": is_valid,
    }


def get_confirmed_core_fields(
    logical_table_id: str | None = None,
) -> tuple[CoreFieldMapping, ...]:
    """Return only fields approved for the Structured Tool."""

    if logical_table_id is not None and logical_table_id not in OFFICIAL_TABLE_COLUMN_COUNTS:
        raise KeyError(f"unknown logical_table_id: {logical_table_id}")
    return tuple(
        entry
        for entry in CORE_FIELD_MAPPINGS
        if entry.semantic_status is SemanticStatus.CONFIRMED
        and (logical_table_id is None or entry.logical_table_id == logical_table_id)
    )


def get_confirmed_field_map(
    logical_table_id: str | None = None,
) -> Mapping[str, CoreFieldMapping]:
    """Return an immutable semantic-key allowlist for query validation."""

    return MappingProxyType(
        {
            entry.semantic_field_key: entry
            for entry in get_confirmed_core_fields(logical_table_id)
        }
    )


def get_core_mapping_summary() -> dict[str, Any]:
    """Summarize reviewed entries while treating all absent columns as unmapped."""

    status_counts = Counter(entry.semantic_status.value for entry in CORE_FIELD_MAPPINGS)
    status_counts[SemanticStatus.UNMAPPED.value] += (
        OFFICIAL_COLUMN_COUNT - len(CORE_FIELD_MAPPINGS)
    )

    table_summary: dict[str, dict[str, int]] = {}
    for table_id, official_count in OFFICIAL_TABLE_COLUMN_COUNTS.items():
        table_entries = tuple(
            entry for entry in CORE_FIELD_MAPPINGS if entry.logical_table_id == table_id
        )
        table_counts = Counter(entry.semantic_status.value for entry in table_entries)
        table_counts[SemanticStatus.UNMAPPED.value] += official_count - len(table_entries)
        table_summary[table_id] = {
            "official_column_count": official_count,
            "reviewed_entry_count": len(table_entries),
            "CONFIRMED": table_counts[SemanticStatus.CONFIRMED.value],
            "NEED_REVIEW": table_counts[SemanticStatus.NEED_REVIEW.value],
            "UNMAPPED": table_counts[SemanticStatus.UNMAPPED.value],
        }

    return {
        "official_column_count": OFFICIAL_COLUMN_COUNT,
        "reviewed_entry_count": len(CORE_FIELD_MAPPINGS),
        "agent_allowed_field_count": len(get_confirmed_core_fields()),
        "semantic_status_counts": {
            status.value: status_counts[status.value] for status in SemanticStatus
        },
        "table_status_counts": table_summary,
    }


def build_core_field_registry() -> dict[str, Any]:
    """Return the review result in a stable JSON-ready report shape."""

    return {
        "registry_format_version": "1.0",
        "policy": {
            "evidence": "official_schema_display_name_and_declared_type",
            "agent_field_selection": "CONFIRMED_ONLY",
            "unlisted_official_columns": "UNMAPPED",
            "semantic_keys": "TABLE_SCOPED_NO_CROSS_PRODUCT_MERGE",
            "numeric_values": "SOURCE_NATIVE_NO_UNIT_OR_SCALE_CONVERSION",
            "text_dates": "NO_TEMPORAL_OPERATIONS",
        },
        "entries": [entry.to_dict() for entry in CORE_FIELD_MAPPINGS],
        "summary": get_core_mapping_summary(),
        "validation": validate_core_field_registry(),
    }


__all__ = [
    "ALLOWED_OPERATIONS",
    "CORE_FIELD_MAPPINGS",
    "CoreFieldMapping",
    "CoreUnitStatus",
    "OFFICIAL_COLUMN_COUNT",
    "OFFICIAL_TABLE_COLUMN_COUNTS",
    "SemanticStatus",
    "build_core_field_registry",
    "get_confirmed_core_fields",
    "get_confirmed_field_map",
    "get_core_mapping_summary",
    "validate_core_field_registry",
]
