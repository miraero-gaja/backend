"""Deterministic G2-A typed-staging primitives.

This package is pure Python and does not connect to a database or modify source
workbooks.  Public imports are collected here so report and coverage builders
do not depend on module internals.
"""

from .lineage import (
    SOURCE_ROW_ID_VERSION,
    SourceLineage,
    build_source_lineage,
    derive_source_row_id,
)
from .models import (
    CodeStatus,
    MappingStatus,
    NullPolicy,
    ParseFailurePolicy,
    ParseResult,
    ParseStatus,
    TargetType,
    TransformPolicy,
    TypedRule,
    UnitStatus,
    WhitespacePolicy,
)
from .normalizer import (
    InvalidTypedRuleError,
    TypedNormalizer,
    normalize_value,
    normalize_values,
)
from .runner import G2ARunnerError, run_g2a
from .type_rules import (
    build_typed_rule,
    canonicalize_declared_type,
    is_supported_rule,
    resolve_target_type,
    transform_policy_for,
)
from .whitespace import (
    TrimStatus,
    WhitespaceAnalysis,
    analyze_trim_impact,
    analyze_whitespace,
)

__all__ = [
    "SOURCE_ROW_ID_VERSION",
    "CodeStatus",
    "InvalidTypedRuleError",
    "G2ARunnerError",
    "MappingStatus",
    "NullPolicy",
    "ParseFailurePolicy",
    "ParseResult",
    "ParseStatus",
    "SourceLineage",
    "TargetType",
    "TransformPolicy",
    "TrimStatus",
    "TypedNormalizer",
    "TypedRule",
    "UnitStatus",
    "WhitespaceAnalysis",
    "WhitespacePolicy",
    "analyze_trim_impact",
    "analyze_whitespace",
    "build_source_lineage",
    "build_typed_rule",
    "canonicalize_declared_type",
    "derive_source_row_id",
    "is_supported_rule",
    "normalize_value",
    "normalize_values",
    "resolve_target_type",
    "run_g2a",
    "transform_policy_for",
]
