"""PRBD duration-family alias disambiguation (20260824 official schema).

The 2026-08-24 official PRBD01N001 schema declares three distinct
duration/convexity columns (dur, ndy_dur, cov). "익일 듀레이션" textually
embeds the shorter "듀레이션" alias, so a naive substring match against
``_FIELD_ALIASES`` legitimately returns both the ndy_dur and dur
candidates for "국내채권 익일 듀레이션 3 이하". ``field_alias_matches``
resolves that specific case by keeping only the most specific match --
but the resolution is span-aware, not a blanket "shorter alias always
loses" rule: when "듀레이션" also occurs standalone in the same query,
separate from any "익일 듀레이션" occurrence (e.g. "듀레이션과 익일
듀레이션 비교"), both fields must survive so the caller's existing
multi-field ambiguity / fail-closed policy still applies. The tests below
pin both the "one alias wins" and the "both aliases must be preserved"
cases, confirm the resolution does not depend on ``_FIELD_ALIASES``
declaration order, and confirm no field-approval status (operation
openness, unit/value-domain status) changed as a side effect.
"""

from __future__ import annotations

import itertools

import pytest

from mappings.aliases.registry import (
    FieldAlias,
    _select_longest_matches,
    field_alias_matches,
    normalize_alias_text,
)
from mappings.semantic.models import OperationStatus
from mappings.semantic.registry import SEMANTIC_FIELD_APPROVALS


@pytest.mark.parametrize(
    ("alias_text", "semantic_key"),
    (
        ("듀레이션", "prbd.dur_unresolved"),
        ("duration", "prbd.dur_unresolved"),
        ("컨벡시티", "prbd.cov_unresolved"),
        ("위험등급", "prbd.pd_risk_gcd_unresolved"),
        ("익일 듀레이션", "prbd.ndy_dur_unresolved"),
    ),
)
def test_prbd_alias_resolves_to_exactly_one_semantic_key(
    alias_text: str,
    semantic_key: str,
) -> None:
    """Every registered PRBD alias -- including "익일 듀레이션", which
    textually embeds the shorter "듀레이션" alias -- must resolve to
    exactly one semantic key when it is the only field mentioned."""

    matches = field_alias_matches("PRBD01N001", alias_text)

    assert len(matches) == 1
    assert matches[0].semantic_keys == (semantic_key,)


def test_ndy_dur_alias_alone_is_the_sole_match_in_a_full_query_sentence() -> None:
    """"익일 듀레이션" embedded in a real query sentence, with no separate
    standalone "듀레이션" occurrence, must resolve to ndy_dur alone."""

    matches = field_alias_matches("PRBD01N001", "국내채권 익일 듀레이션 3 이하")

    assert len(matches) == 1
    assert matches[0].semantic_keys == ("prbd.ndy_dur_unresolved",)


def test_dur_alias_alone_is_the_sole_match_in_a_full_query_sentence() -> None:
    matches = field_alias_matches("PRBD01N001", "국내채권 듀레이션 3 이하")

    assert len(matches) == 1
    assert matches[0].semantic_keys == ("prbd.dur_unresolved",)


def test_cov_alias_is_unambiguous_even_within_a_full_query_sentence() -> None:
    matches = field_alias_matches("PRBD01N001", "국내채권 컨벡시티 3 이하")

    assert len(matches) == 1
    assert matches[0].semantic_keys == ("prbd.cov_unresolved",)


def test_dur_and_ndy_dur_both_named_separately_are_both_preserved() -> None:
    """When "듀레이션" and "익일 듀레이션" are each mentioned as their own,
    non-nested occurrence (e.g. comparing the two), the shorter "듀레이션"
    occurrence sitting outside the "익일 듀레이션" span must NOT be
    silently dropped: both fields are genuinely named, so both semantic
    keys must be returned and the caller's ambiguity / fail-closed policy
    is expected to apply.
    """

    matches = field_alias_matches(
        "PRBD01N001", "국내채권 듀레이션과 익일 듀레이션 비교"
    )

    assert {match.semantic_keys for match in matches} == {
        ("prbd.dur_unresolved",),
        ("prbd.ndy_dur_unresolved",),
    }


def test_cov_and_dur_named_together_are_both_preserved() -> None:
    """"컨벡시티" and "듀레이션" never textually overlap, so mentioning
    both must always return both candidates regardless of span
    computation."""

    matches = field_alias_matches(
        "PRBD01N001", "국내채권 컨벡시티와 듀레이션 비교"
    )

    assert {match.semantic_keys for match in matches} == {
        ("prbd.cov_unresolved",),
        ("prbd.dur_unresolved",),
    }


def test_longest_match_selection_is_span_aware_not_purely_textual() -> None:
    """``_select_longest_matches`` must decide per occurrence, not per
    alias globally: a shorter alias is dropped only where its match sits
    inside a longer alias's match in the same query text. The identical
    candidate set produces different kept results depending on whether the
    shorter alias also has a standalone occurrence in the query.
    """

    dur = FieldAlias("듀레이션", "PRBD01N001", ("prbd.dur_unresolved",))
    ndy_dur = FieldAlias("익일 듀레이션", "PRBD01N001", ("prbd.ndy_dur_unresolved",))

    nested_only = normalize_alias_text("국내채권 익일 듀레이션 3 이하")
    standalone_and_nested = normalize_alias_text(
        "국내채권 듀레이션과 익일 듀레이션 비교"
    )

    nested_kept = _select_longest_matches((dur, ndy_dur), nested_only)
    assert {m.semantic_keys for m in nested_kept} == {("prbd.ndy_dur_unresolved",)}

    both_kept = _select_longest_matches((dur, ndy_dur), standalone_and_nested)
    assert {m.semantic_keys for m in both_kept} == {
        ("prbd.dur_unresolved",),
        ("prbd.ndy_dur_unresolved",),
    }


def test_longest_match_selection_is_independent_of_candidate_order() -> None:
    """``_select_longest_matches`` must depend only on the matched aliases'
    text and where they occur in the query, never on the order candidates
    happen to be passed in -- the generalized replacement for the previous
    declaration-order assumption. This holds for both the "one alias wins"
    case and the "both aliases survive" case.
    """

    dur = FieldAlias("듀레이션", "PRBD01N001", ("prbd.dur_unresolved",))
    ndy_dur = FieldAlias("익일 듀레이션", "PRBD01N001", ("prbd.ndy_dur_unresolved",))
    risk_grade = FieldAlias("위험등급", "PRBD01N001", ("prbd.pd_risk_gcd_unresolved",))
    cov = FieldAlias("컨벡시티", "PRBD01N001", ("prbd.cov_unresolved",))

    nested_only = normalize_alias_text("국내채권 익일 듀레이션 3 이하")
    standalone_and_nested = normalize_alias_text(
        "국내채권 듀레이션과 익일 듀레이션 비교"
    )

    for permutation in itertools.permutations((dur, ndy_dur, risk_grade, cov)):
        kept_keys = {
            match.semantic_keys
            for match in _select_longest_matches(permutation, nested_only)
        }
        assert kept_keys == {("prbd.ndy_dur_unresolved",)}

        kept_keys = {
            match.semantic_keys
            for match in _select_longest_matches(
                permutation, standalone_and_nested
            )
        }
        assert kept_keys == {
            ("prbd.dur_unresolved",),
            ("prbd.ndy_dur_unresolved",),
        }


def test_field_alias_matches_result_is_independent_of_registry_declaration_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reordering the module-level ``_FIELD_ALIASES`` tuple must not change
    which semantic key(s) a query resolves to."""

    import mappings.aliases.registry as registry_module

    reversed_aliases = tuple(reversed(registry_module._FIELD_ALIASES))
    monkeypatch.setattr(registry_module, "_FIELD_ALIASES", reversed_aliases)

    single_field_cases = (
        ("국내채권 익일 듀레이션 3 이하", "prbd.ndy_dur_unresolved"),
        ("국내채권 듀레이션 3 이하", "prbd.dur_unresolved"),
        ("국내채권 컨벡시티 3 이하", "prbd.cov_unresolved"),
        ("국내채권 duration 3 이하", "prbd.dur_unresolved"),
        ("국내채권 위험등급 1 이하", "prbd.pd_risk_gcd_unresolved"),
    )
    for question, expected_key in single_field_cases:
        matches = registry_module.field_alias_matches("PRBD01N001", question)
        assert len(matches) == 1
        assert matches[0].semantic_keys == (expected_key,)

    multi_field_cases = (
        (
            "국내채권 듀레이션과 익일 듀레이션 비교",
            {("prbd.dur_unresolved",), ("prbd.ndy_dur_unresolved",)},
        ),
        (
            "국내채권 컨벡시티와 듀레이션 비교",
            {("prbd.cov_unresolved",), ("prbd.dur_unresolved",)},
        ),
    )
    for question, expected_keys in multi_field_cases:
        matches = registry_module.field_alias_matches("PRBD01N001", question)
        assert {match.semantic_keys for match in matches} == expected_keys


def test_prbd_duration_family_operations_remain_fully_closed() -> None:
    """Resolving alias ambiguity must not newly open any operation or
    approve unit/value-domain status for dur, ndy_dur, or cov."""

    approvals = {
        approval.semantic_key: approval
        for approval in SEMANTIC_FIELD_APPROVALS
        if approval.semantic_key
        in {
            "prbd.dur_unresolved",
            "prbd.ndy_dur_unresolved",
            "prbd.cov_unresolved",
        }
    }

    assert set(approvals) == {
        "prbd.dur_unresolved",
        "prbd.ndy_dur_unresolved",
        "prbd.cov_unresolved",
    }
    for approval in approvals.values():
        assert approval.open_operations == ()
        closed_operations = {
            operation.operation
            for operation in approval.operations
            if operation.status is OperationStatus.CLOSED
        }
        assert closed_operations == {
            "EQ",
            "NE",
            "LT",
            "LE",
            "GT",
            "GE",
            "SORT_ASC",
            "SORT_DESC",
        }
