"""Typed staging value-preservation and strict conversion contracts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pipeline.normalize import (
    InvalidTypedRuleError,
    ParseStatus,
    TargetType,
    TransformPolicy,
    TypedRule,
    build_typed_rule,
    normalize_value,
)


def _rule(declared_type: str) -> TypedRule:
    return build_typed_rule(
        logical_table_id="SYNTHETIC",
        source_column="synthetic_value",
        declared_type=declared_type,
        observed_types=("string",),
    )


@pytest.mark.parametrize(
    ("declared_type", "raw_value"),
    [
        ("text", " 001.2300 "),
        ("numeric", "001.2300"),
        ("numeric", "1,234"),
        ("date", "2026-02-30"),
        ("jsonb", '{"synthetic": true}'),
    ],
)
def test_every_parse_outcome_preserves_the_exact_raw_value(
    declared_type: str,
    raw_value: str,
) -> None:
    result = normalize_value(raw_value, _rule(declared_type))

    assert result.raw_value == raw_value


def test_declared_text_is_preserved_even_when_numeric_looking() -> None:
    raw = "001.2300"
    rule = _rule("text")

    result = normalize_value(raw, rule)

    assert rule.target_type is TargetType.TEXT
    assert result.parse_status is ParseStatus.OK
    assert result.raw_value == raw
    assert result.normalized_value == raw


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("001.2300", Decimal("1.2300")),
        ("-2.5E+3", Decimal("-2.5E+3")),
        (7, Decimal("7")),
        (0.1, Decimal("0.1")),
    ],
)
def test_decimal_conversion_is_exact_and_explicit(
    raw_value: str | int | float,
    expected: Decimal,
) -> None:
    result = normalize_value(raw_value, _rule("numeric"))

    assert result.parse_status is ParseStatus.OK
    assert isinstance(result.normalized_value, Decimal)
    assert result.normalized_value == expected
    if isinstance(raw_value, str) and raw_value == "001.2300":
        assert result.normalized_value.as_tuple().exponent == -4


@pytest.mark.parametrize(
    "raw_value",
    ["1,234", "12%", " 12", "12 ", "NaN", "Infinity", True],
)
def test_decimal_parse_errors_are_not_silently_null_or_coerced(
    raw_value: str | bool,
) -> None:
    result = normalize_value(raw_value, _rule("double precision"))

    assert result.raw_value == raw_value
    assert result.normalized_value is None
    assert result.parse_status is ParseStatus.PARSE_ERROR


@pytest.mark.parametrize("raw_value", [1.5, Decimal("2.1"), "1.0", True])
def test_integer_conversion_rejects_fractional_decimal_syntax_and_boolean(
    raw_value: float | Decimal | str | bool,
) -> None:
    result = normalize_value(raw_value, _rule("bigint"))

    assert result.raw_value == raw_value
    assert result.normalized_value is None
    assert result.parse_status is ParseStatus.PARSE_ERROR


@pytest.mark.parametrize(
    ("declared_type", "raw_value", "expected"),
    [
        (
            "timestamp without time zone",
            "2026-08-19 14:05:06.123456",
            datetime(2026, 8, 19, 14, 5, 6, 123456),
        ),
        (
            "timestamp with time zone",
            "2026-08-19T14:05:06+09:00",
            datetime(
                2026,
                8,
                19,
                14,
                5,
                6,
                tzinfo=timezone(timedelta(hours=9)),
            ),
        ),
        ("date", "2026-08-19", date(2026, 8, 19)),
    ],
)
def test_date_and_timestamp_parse_success(
    declared_type: str,
    raw_value: str,
    expected: date | datetime,
) -> None:
    result = normalize_value(raw_value, _rule(declared_type))

    assert result.parse_status is ParseStatus.OK
    assert result.normalized_value == expected


@pytest.mark.parametrize(
    ("declared_type", "raw_value"),
    [
        ("date", "2026-02-30"),
        ("date", "20260819"),
        ("timestamp without time zone", "2026-08-19T14:05:06+09:00"),
        ("timestamp with time zone", "2026-08-19 14:05:06"),
        ("timestamp without time zone", "2026/08/19 14:05:06"),
    ],
)
def test_date_and_timestamp_parse_failure_is_explicit(
    declared_type: str,
    raw_value: str,
) -> None:
    result = normalize_value(raw_value, _rule(declared_type))

    assert result.raw_value == raw_value
    assert result.normalized_value is None
    assert result.parse_status is ParseStatus.PARSE_ERROR


@pytest.mark.parametrize(
    ("raw_value", "status"),
    [
        (None, ParseStatus.MISSING),
        ("", ParseStatus.EMPTY),
        ("   \t", ParseStatus.WHITESPACE_ONLY),
    ],
)
def test_missing_empty_and_whitespace_only_remain_distinct(
    raw_value: str | None,
    status: ParseStatus,
) -> None:
    result = normalize_value(raw_value, _rule("text"))

    assert result.raw_value == raw_value
    assert result.normalized_value is None
    assert result.parse_status is status


def test_unsupported_declared_type_is_blocked_without_text_fallback() -> None:
    raw = "must-not-fall-through"
    rule = _rule("jsonb")

    result = normalize_value(raw, rule)

    assert rule.target_type is TargetType.UNSUPPORTED
    assert rule.transform_policy is TransformPolicy.BLOCK_UNSUPPORTED
    assert result.raw_value == raw
    assert result.normalized_value is None
    assert result.parse_status is ParseStatus.NOT_APPLICABLE


def test_incompatible_manually_constructed_conversion_rule_is_rejected() -> None:
    unsafe_rule = TypedRule(
        logical_table_id="SYNTHETIC",
        source_column="synthetic_value",
        declared_type="text",
        observed_types=(),
        target_type=TargetType.TEXT,
        transform_policy=TransformPolicy.PARSE_DECIMAL,
    )

    with pytest.raises(InvalidTypedRuleError):
        normalize_value("1", unsafe_rule)


def test_manual_rule_cannot_promote_declared_text_to_decimal() -> None:
    unsafe_rule = TypedRule(
        logical_table_id="SYNTHETIC",
        source_column="synthetic_value",
        declared_type="text",
        observed_types=("string",),
        target_type=TargetType.DECIMAL,
        transform_policy=TransformPolicy.PARSE_DECIMAL,
    )

    with pytest.raises(InvalidTypedRuleError, match="resolves to TEXT"):
        normalize_value("001.2300", unsafe_rule)
