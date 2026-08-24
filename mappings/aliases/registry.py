"""Reviewed, deliberately small alias baseline for structured QA.

Aliases only select existing table-scoped semantic keys.  They do not approve
units, code meanings, value domains, or operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_SPACE = re.compile(r"\s+")


def normalize_alias_text(value: str) -> str:
    """Case-fold and remove spacing without changing numbers or punctuation."""

    return _SPACE.sub("", value).casefold()


@dataclass(frozen=True, slots=True)
class ProductAlias:
    alias: str
    display_name: str
    logical_table_id: str


@dataclass(frozen=True, slots=True)
class FieldAlias:
    alias: str
    logical_table_id: str
    semantic_keys: tuple[str, ...]


_PRODUCT_ALIASES: tuple[ProductAlias, ...] = (
    ProductAlias("국내채권", "국내채권", "PRBD01N001"),
    ProductAlias("국내ETF", "국내 ETF", "PREF01N001"),
    ProductAlias("해외ETF", "해외 ETF", "PREF02N001"),
    ProductAlias("공모펀드", "공모펀드", "PRFD01N001"),
)


_FIELD_ALIASES: tuple[FieldAlias, ...] = (
    FieldAlias("상품코드", "PREF01N001", ("pref01.product_code",)),
    FieldAlias("상품명", "PREF01N001", ("pref01.product_name",)),
    FieldAlias("AUM", "PREF01N001", ("pref01.aum_latest",)),
    FieldAlias(
        "상장주식수",
        "PREF01N001",
        ("pref01.listed_share_count",),
    ),
    FieldAlias("AUM", "PREF02N001", ("pref02.aum_latest",)),
    FieldAlias("총보수", "PREF02N001", ("pref02.expense_ratio",)),
    FieldAlias(
        "위험등급",
        "PRBD01N001",
        ("prbd.pd_risk_gcd_unresolved",),
    ),
    FieldAlias(
        "듀레이션",
        "PRBD01N001",
        (
            "prbd.dur_unresolved",
            "prbd.ndy_dur_unresolved",
            "prbd.cov_unresolved",
        ),
    ),
    FieldAlias(
        "duration",
        "PRBD01N001",
        (
            "prbd.dur_unresolved",
            "prbd.ndy_dur_unresolved",
            "prbd.cov_unresolved",
        ),
    ),
    FieldAlias("상품코드", "PRFD01N001", ("prfd.product_code",)),
    FieldAlias("상품명", "PRFD01N001", ("prfd.product_name",)),
    FieldAlias("순자산", "PRFD01N001", ("prfd.net_assets",)),
)


def product_alias_matches(text: str) -> tuple[ProductAlias, ...]:
    normalized = normalize_alias_text(text)
    return tuple(
        item
        for item in _PRODUCT_ALIASES
        if normalize_alias_text(item.alias) in normalized
    )


def field_alias_matches(
    logical_table_id: str,
    text: str,
) -> tuple[FieldAlias, ...]:
    normalized = normalize_alias_text(text)
    return tuple(
        item
        for item in _FIELD_ALIASES
        if item.logical_table_id == logical_table_id
        and normalize_alias_text(item.alias) in normalized
    )


__all__ = [
    "FieldAlias",
    "ProductAlias",
    "field_alias_matches",
    "normalize_alias_text",
    "product_alias_matches",
]
