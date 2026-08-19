"""Pure, row-local typed normalization with explicit failure states."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .models import (
    ParseResult,
    ParseStatus,
    SourceScalar,
    TargetType,
    TransformPolicy,
    TypedRule,
)
from .type_rules import canonicalize_declared_type, resolve_target_type


_DECIMAL_LITERAL = re.compile(
    r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?",
    re.ASCII,
)
_INTEGER_LITERAL = re.compile(r"[+-]?\d+", re.ASCII)
_DATE_LITERAL = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_NAIVE_TIMESTAMP_LITERAL = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?",
    re.ASCII,
)
_AWARE_TIMESTAMP_LITERAL = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
    re.ASCII,
)

_EXPECTED_POLICIES = {
    TargetType.TEXT: TransformPolicy.PRESERVE_TEXT,
    TargetType.DECIMAL: TransformPolicy.PARSE_DECIMAL,
    TargetType.INTEGER: TransformPolicy.PARSE_INTEGER,
    TargetType.TIMESTAMP: TransformPolicy.PARSE_TIMESTAMP,
    TargetType.DATE: TransformPolicy.PARSE_DATE,
    TargetType.UNSUPPORTED: TransformPolicy.BLOCK_UNSUPPORTED,
}


class InvalidTypedRuleError(ValueError):
    """Raised when a manually constructed rule requests an unsafe conversion."""


def _validate_rule(rule: TypedRule) -> None:
    declared_target = resolve_target_type(rule.declared_type)
    if rule.target_type is not declared_target:
        raise InvalidTypedRuleError(
            f"declared type {rule.declared_type!r} resolves to "
            f"{declared_target.value}, not {rule.target_type.value}"
        )
    expected = _EXPECTED_POLICIES[rule.target_type]
    if rule.transform_policy is not expected:
        raise InvalidTypedRuleError(
            f"{rule.target_type.value} requires {expected.value}; "
            f"received {rule.transform_policy.value}"
        )


def _missing_result(raw_value: SourceScalar) -> ParseResult | None:
    if raw_value is None:
        return ParseResult(raw_value, None, ParseStatus.MISSING)
    if isinstance(raw_value, str):
        if raw_value == "":
            return ParseResult(raw_value, None, ParseStatus.EMPTY)
        if raw_value.isspace():
            return ParseResult(raw_value, None, ParseStatus.WHITESPACE_ONLY)
    return None


def _parse_decimal(raw_value: SourceScalar) -> Decimal | None:
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, Decimal):
        return raw_value if raw_value.is_finite() else None
    if isinstance(raw_value, int):
        return Decimal(raw_value)
    if isinstance(raw_value, float):
        if not math.isfinite(raw_value):
            return None
        return Decimal(str(raw_value))
    if not isinstance(raw_value, str) or not _DECIMAL_LITERAL.fullmatch(raw_value):
        return None
    try:
        parsed = Decimal(raw_value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _parse_integer(raw_value: SourceScalar) -> int | None:
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, Decimal):
        if raw_value.is_finite() and raw_value == raw_value.to_integral_value():
            return int(raw_value)
        return None
    if isinstance(raw_value, float):
        if math.isfinite(raw_value) and raw_value.is_integer():
            return int(raw_value)
        return None
    if isinstance(raw_value, str) and _INTEGER_LITERAL.fullmatch(raw_value):
        try:
            return int(raw_value)
        except ValueError:
            return None
    return None


def _timezone_kind(declared_type: str) -> str:
    canonical = canonicalize_declared_type(declared_type)
    if "without time zone" in canonical:
        return "NAIVE"
    if "with time zone" in canonical:
        return "AWARE"
    return "EITHER"


def _datetime_matches_timezone(value: datetime, kind: str) -> bool:
    aware = value.tzinfo is not None and value.utcoffset() is not None
    if kind == "NAIVE":
        return not aware
    if kind == "AWARE":
        return aware
    return True


def _parse_timestamp(raw_value: SourceScalar, declared_type: str) -> datetime | None:
    kind = _timezone_kind(declared_type)
    if isinstance(raw_value, datetime):
        return raw_value if _datetime_matches_timezone(raw_value, kind) else None
    if not isinstance(raw_value, str):
        return None

    if kind == "NAIVE":
        pattern = _NAIVE_TIMESTAMP_LITERAL
    elif kind == "AWARE":
        pattern = _AWARE_TIMESTAMP_LITERAL
    else:
        pattern = (
            _AWARE_TIMESTAMP_LITERAL
            if _AWARE_TIMESTAMP_LITERAL.fullmatch(raw_value)
            else _NAIVE_TIMESTAMP_LITERAL
        )
    if not pattern.fullmatch(raw_value):
        return None

    iso_value = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return None
    return parsed if _datetime_matches_timezone(parsed, kind) else None


def _parse_date(raw_value: SourceScalar) -> date | None:
    if isinstance(raw_value, datetime):
        return None
    if isinstance(raw_value, date):
        return raw_value
    if not isinstance(raw_value, str) or not _DATE_LITERAL.fullmatch(raw_value):
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def normalize_value(raw_value: SourceScalar, rule: TypedRule) -> ParseResult:
    """Apply one rule without trimming, imputing, or hiding parse failures.

    Unsupported declared types are blocked with ``NOT_APPLICABLE`` and no
    normalized value.  Invalid target/policy combinations raise before any
    value conversion is attempted.
    """

    _validate_rule(rule)
    missing = _missing_result(raw_value)
    if missing is not None:
        return missing

    if rule.target_type is TargetType.UNSUPPORTED:
        return ParseResult(raw_value, None, ParseStatus.NOT_APPLICABLE)
    if rule.target_type is TargetType.TEXT:
        return ParseResult(raw_value, raw_value, ParseStatus.OK)

    if rule.target_type is TargetType.DECIMAL:
        normalized = _parse_decimal(raw_value)
    elif rule.target_type is TargetType.INTEGER:
        normalized = _parse_integer(raw_value)
    elif rule.target_type is TargetType.TIMESTAMP:
        normalized = _parse_timestamp(raw_value, rule.declared_type)
    elif rule.target_type is TargetType.DATE:
        normalized = _parse_date(raw_value)
    else:  # pragma: no cover - exhaustive protection for a future enum member
        raise InvalidTypedRuleError(f"unhandled target type: {rule.target_type!r}")

    status = ParseStatus.OK if normalized is not None else ParseStatus.PARSE_ERROR
    return ParseResult(raw_value, normalized, status)


def normalize_values(
    values: Iterable[SourceScalar],
    rule: TypedRule,
) -> Iterator[ParseResult]:
    """Lazily normalize values so callers need not retain source rows."""

    for value in values:
        yield normalize_value(value, rule)


@dataclass(frozen=True, slots=True)
class TypedNormalizer:
    """Small callable wrapper for repeatedly applying one immutable rule."""

    rule: TypedRule

    def normalize(self, raw_value: SourceScalar) -> ParseResult:
        return normalize_value(raw_value, self.rule)

    def __call__(self, raw_value: SourceScalar) -> ParseResult:
        return self.normalize(raw_value)


__all__ = [
    "InvalidTypedRuleError",
    "TypedNormalizer",
    "normalize_value",
    "normalize_values",
]
