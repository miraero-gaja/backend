"""Schema-declared type resolution for deterministic typed staging.

Observed value shape is recorded as evidence, but it never promotes a text
column into a numeric or date column.  Only the declared schema type selects a
conversion policy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import (
    CodeStatus,
    MappingStatus,
    NullPolicy,
    ParseFailurePolicy,
    TargetType,
    TransformPolicy,
    TypedRule,
    UnitStatus,
    WhitespacePolicy,
)


_NUMERIC_DECLARATION = re.compile(
    r"(?:numeric|decimal)(?:\(\d+(?:,\d+)?\))?",
    re.ASCII,
)
_TEXT_DECLARATION = re.compile(
    r"(?:text|varchar(?:\(\d+\))?|character varying(?:\(\d+\))?)",
    re.ASCII,
)
_TIMESTAMP_DECLARATION = re.compile(
    r"timestamp(?:\(\d+\))?(?: (?:with|without) time zone)?",
    re.ASCII,
)


def canonicalize_declared_type(declared_type: str) -> str:
    """Canonicalize only type-expression spelling, never a source cell value."""

    if not isinstance(declared_type, str) or not declared_type.strip():
        raise ValueError("declared_type must be a non-empty string")
    collapsed = " ".join(declared_type.casefold().split())
    return re.sub(r"\s*([(),])\s*", r"\1", collapsed)


def resolve_target_type(declared_type: str) -> TargetType:
    """Resolve a target strictly from a declared schema type."""

    canonical = canonicalize_declared_type(declared_type)
    if _TEXT_DECLARATION.fullmatch(canonical):
        return TargetType.TEXT
    if _NUMERIC_DECLARATION.fullmatch(canonical) or canonical == "double precision":
        return TargetType.DECIMAL
    if canonical == "bigint":
        return TargetType.INTEGER
    if _TIMESTAMP_DECLARATION.fullmatch(canonical):
        return TargetType.TIMESTAMP
    if canonical == "date":
        return TargetType.DATE
    return TargetType.UNSUPPORTED


def transform_policy_for(target_type: TargetType) -> TransformPolicy:
    """Return the sole permitted transform for a technical target type."""

    policies = {
        TargetType.TEXT: TransformPolicy.PRESERVE_TEXT,
        TargetType.DECIMAL: TransformPolicy.PARSE_DECIMAL,
        TargetType.INTEGER: TransformPolicy.PARSE_INTEGER,
        TargetType.TIMESTAMP: TransformPolicy.PARSE_TIMESTAMP,
        TargetType.DATE: TransformPolicy.PARSE_DATE,
        TargetType.UNSUPPORTED: TransformPolicy.BLOCK_UNSUPPORTED,
    }
    return policies[target_type]


def build_typed_rule(
    *,
    logical_table_id: str,
    source_column: str,
    declared_type: str,
    observed_types: Iterable[str] = (),
    occurrence: int = 1,
    qualified_name: str | None = None,
    unit_status: UnitStatus = UnitStatus.UNMAPPED,
    code_status: CodeStatus = CodeStatus.UNMAPPED,
    mapping_status: MappingStatus = MappingStatus.UNMAPPED,
) -> TypedRule:
    """Build a conservative occurrence-aware rule from schema metadata.

    ``observed_types`` cannot affect the target or transform.  In particular,
    numeric-looking text remains ``TEXT`` when the schema declares ``text``.
    """

    target_type = resolve_target_type(declared_type)
    return TypedRule(
        logical_table_id=logical_table_id,
        source_column=source_column,
        occurrence=occurrence,
        qualified_name=qualified_name,
        declared_type=declared_type,
        observed_types=tuple(observed_types),
        target_type=target_type,
        transform_policy=transform_policy_for(target_type),
        null_policy=NullPolicy.PRESERVE_MISSING,
        whitespace_policy=WhitespacePolicy.PRESERVE,
        parse_failure_policy=ParseFailurePolicy.RECORD_PARSE_ERROR,
        unit_status=unit_status,
        code_status=code_status,
        mapping_status=mapping_status,
    )


def is_supported_rule(rule: TypedRule) -> bool:
    """Return whether the rule permits a conversion or exact text preservation."""

    return (
        rule.target_type is not TargetType.UNSUPPORTED
        and rule.transform_policy is not TransformPolicy.BLOCK_UNSUPPORTED
    )


__all__ = [
    "build_typed_rule",
    "canonicalize_declared_type",
    "is_supported_rule",
    "resolve_target_type",
    "transform_policy_for",
]
