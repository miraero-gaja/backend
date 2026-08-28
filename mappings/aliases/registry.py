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


# Declaration order is not semantically meaningful: field_alias_matches below
# resolves overlapping aliases (e.g. "익일 듀레이션" containing "듀레이션")
# by span-aware occurrence containment within the query text, not by tuple
# position. Reordering this tuple must not change any resolution result.
_FIELD_ALIASES: tuple[FieldAlias, ...] = (
    FieldAlias("상품코드", "PRBD01N001", ("prbd.product_code",)),
    FieldAlias("채권종목번호", "PRBD01N001", ("prbd.product_code",)),
    FieldAlias("상품명", "PRBD01N001", ("prbd.product_name",)),
    FieldAlias("채권명", "PRBD01N001", ("prbd.product_name",)),
    FieldAlias(
        "상품중분류명",
        "PRBD01N001",
        ("prbd.product_mid_category_name",),
    ),
    FieldAlias(
        "상품소분류명",
        "PRBD01N001",
        ("prbd.product_sub_category_name",),
    ),
    FieldAlias("상품코드", "PREF01N001", ("pref01.product_code",)),
    FieldAlias("상품명", "PREF01N001", ("pref01.product_name",)),
    FieldAlias("운용사", "PREF01N001", ("pref01.fund_manager_name",)),
    FieldAlias("기초지수", "PREF01N001", ("pref01.base_index_name",)),
    FieldAlias("운용전략", "PREF01N001", ("pref01.strategy_name",)),
    FieldAlias(
        "투자자산군",
        "PREF01N001",
        ("pref01.investment_asset_type",),
    ),
    FieldAlias("투자지역", "PREF01N001", ("pref01.investment_region",)),
    FieldAlias("거래소명", "PREF01N001", ("pref01.exchange_name",)),
    FieldAlias("상품거래시장", "PREF01N001", ("pref01.market_name",)),
    FieldAlias("상품등급명", "PREF01N001", ("pref01.risk_grade_name",)),
    FieldAlias("일간갱신일자", "PREF01N001", ("pref01.daily_updated_at",)),
    FieldAlias("AUM", "PREF01N001", ("pref01.aum_latest",)),
    FieldAlias("총보수", "PREF01N001", ("pref01.total_fee_rate",)),
    FieldAlias(
        "상장주식수",
        "PREF01N001",
        ("pref01.listed_share_count",),
    ),
    FieldAlias("상품명", "PREF02N001", ("pref02.product_name",)),
    FieldAlias(
        "해외ETF RIC",
        "PREF02N001",
        ("pref02.product_identifier",),
    ),
    FieldAlias("운용사", "PREF02N001", ("pref02.fund_manager_name",)),
    FieldAlias("기초지수", "PREF02N001", ("pref02.base_index_name",)),
    FieldAlias(
        "투자자산군",
        "PREF02N001",
        ("pref02.investment_asset_type",),
    ),
    FieldAlias("투자지역", "PREF02N001", ("pref02.investment_region",)),
    FieldAlias("AUM", "PREF02N001", ("pref02.aum_latest",)),
    FieldAlias("총보수", "PREF02N001", ("pref02.expense_ratio",)),
    FieldAlias(
        "위험등급",
        "PRBD01N001",
        ("prbd.pd_risk_gcd_unresolved",),
    ),
    FieldAlias(
        "익일 듀레이션",
        "PRBD01N001",
        ("prbd.ndy_dur_unresolved",),
    ),
    FieldAlias(
        "듀레이션",
        "PRBD01N001",
        ("prbd.dur_unresolved",),
    ),
    FieldAlias(
        "duration",
        "PRBD01N001",
        ("prbd.dur_unresolved",),
    ),
    FieldAlias(
        "컨벡시티",
        "PRBD01N001",
        ("prbd.cov_unresolved",),
    ),
    FieldAlias("상품코드", "PRFD01N001", ("prfd.product_code",)),
    FieldAlias("상품명", "PRFD01N001", ("prfd.product_name",)),
    FieldAlias("펀드투자지역", "PRFD01N001", ("prfd.investment_region",)),
    FieldAlias(
        "사모공모구분",
        "PRFD01N001",
        ("prfd.public_private_category",),
    ),
    FieldAlias(
        "제로인펀드투자위험등급명",
        "PRFD01N001",
        ("prfd.risk_grade_name",),
    ),
    FieldAlias("벤치마크명", "PRFD01N001", ("prfd.benchmark_name",)),
    FieldAlias("클래스명", "PRFD01N001", ("prfd.class_name",)),
    FieldAlias(
        "클래스판매채널",
        "PRFD01N001",
        ("prfd.class_sales_channel_name",),
    ),
    FieldAlias("제로인유형명", "PRFD01N001", ("prfd.zero_in_type_name",)),
    FieldAlias("순자산", "PRFD01N001", ("prfd.net_assets",)),
)


def product_alias_matches(text: str) -> tuple[ProductAlias, ...]:
    normalized = normalize_alias_text(text)
    return tuple(
        item
        for item in _PRODUCT_ALIASES
        if normalize_alias_text(item.alias) in normalized
    )


def _find_occurrence_spans(needle: str, haystack: str) -> tuple[tuple[int, int], ...]:
    """Every (possibly overlapping) start/end span where ``needle`` occurs
    in ``haystack``."""

    if not needle:
        return ()
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            break
        spans.append((index, index + len(needle)))
        start = index + 1
    return tuple(spans)


def _select_longest_matches(
    candidates: tuple[FieldAlias, ...],
    normalized_query: str,
) -> tuple[FieldAlias, ...]:
    """Keep a matched alias only if it has an occurrence in the query text
    that is not fully nested inside a longer matched alias's occurrence.

    This is span-aware, not purely textual: two aliases whose text happens
    to be substring-related (e.g. "듀레이션" inside "익일 듀레이션") only
    have the shorter one dropped at the specific place in the query where
    it sits inside the longer alias's match. A standalone occurrence of the
    shorter alias elsewhere in the same query -- e.g. "듀레이션과 익일
    듀레이션 비교", where "듀레이션" also appears on its own, separate from
    the "익일 듀레이션" occurrence -- is not covered by anything longer and
    survives, so both fields are returned and the caller's existing
    multi-field ambiguity / fail-closed policy still applies.

    Two aliases that never textually overlap (including same-length aliases
    naming genuinely different fields, e.g. "컨벡시티" and "듀레이션") are
    unaffected by this function: neither can cover the other's occurrence,
    so both are always kept.

    The result depends only on each matched alias's text and where it
    occurs in ``normalized_query`` -- never on the order candidates are
    passed in -- so reordering ``_FIELD_ALIASES`` cannot change the
    outcome.
    """

    occurrences = tuple(
        (candidate, normalize_alias_text(candidate.alias))
        for candidate in candidates
    )
    spans_by_index = tuple(
        _find_occurrence_spans(text, normalized_query) for _, text in occurrences
    )

    kept: list[FieldAlias] = []
    for index, (candidate, text) in enumerate(occurrences):
        own_spans = spans_by_index[index]
        has_uncovered_occurrence = False
        for own_start, own_end in own_spans:
            covered_by_a_longer_match = False
            for other_index, (_, other_text) in enumerate(occurrences):
                if other_index == index or len(other_text) <= len(text):
                    continue
                for other_start, other_end in spans_by_index[other_index]:
                    if other_start <= own_start and own_end <= other_end:
                        covered_by_a_longer_match = True
                        break
                if covered_by_a_longer_match:
                    break
            if not covered_by_a_longer_match:
                has_uncovered_occurrence = True
                break
        if has_uncovered_occurrence:
            kept.append(candidate)
    return tuple(kept)


def field_alias_matches(
    logical_table_id: str,
    text: str,
) -> tuple[FieldAlias, ...]:
    normalized = normalize_alias_text(text)
    candidates = tuple(
        item
        for item in _FIELD_ALIASES
        if item.logical_table_id == logical_table_id
        and normalize_alias_text(item.alias) in normalized
    )
    return _select_longest_matches(candidates, normalized)


__all__ = [
    "FieldAlias",
    "ProductAlias",
    "field_alias_matches",
    "normalize_alias_text",
    "product_alias_matches",
]
