"""Typed staging contracts that preserve source values and parse outcomes.

The contracts in this module are deliberately independent of a database or a
financial ontology.  They describe only transformations justified by the
source schema and keep the original value alongside every normalized value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ParseStatus(StrEnum):
    """Outcome of applying one typed-staging rule to one source value."""

    OK = "OK"
    MISSING = "MISSING"
    EMPTY = "EMPTY"
    WHITESPACE_ONLY = "WHITESPACE_ONLY"
    PARSE_ERROR = "PARSE_ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TargetType(StrEnum):
    """Canonical technical types supported by the G2-A staging contract."""

    TEXT = "TEXT"
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    TIMESTAMP = "TIMESTAMP"
    DATE = "DATE"
    UNSUPPORTED = "UNSUPPORTED"


class TransformPolicy(StrEnum):
    """The only transformations implemented by the deterministic normalizer."""

    PRESERVE_TEXT = "PRESERVE_TEXT"
    PARSE_DECIMAL = "PARSE_DECIMAL"
    PARSE_INTEGER = "PARSE_INTEGER"
    PARSE_TIMESTAMP = "PARSE_TIMESTAMP"
    PARSE_DATE = "PARSE_DATE"
    BLOCK_UNSUPPORTED = "BLOCK_UNSUPPORTED"


class NullPolicy(StrEnum):
    """Null handling is observational; a missing value is never imputed."""

    PRESERVE_MISSING = "PRESERVE_MISSING"


class WhitespacePolicy(StrEnum):
    """Raw and normalized text retain their exact whitespace in G2-A."""

    PRESERVE = "PRESERVE"


class ParseFailurePolicy(StrEnum):
    """A failed parse remains explicit instead of becoming a silent null."""

    RECORD_PARSE_ERROR = "RECORD_PARSE_ERROR"


class MappingStatus(StrEnum):
    """Evidence level for a source-to-concept mapping."""

    CONFIRMED = "CONFIRMED"
    CANDIDATE = "CANDIDATE"
    UNMAPPED = "UNMAPPED"


class UnitStatus(StrEnum):
    """Evidence level for a unit interpretation."""

    CONFIRMED = "CONFIRMED"
    CANDIDATE = "CANDIDATE"
    UNMAPPED = "UNMAPPED"


class CodeStatus(StrEnum):
    """Evidence level for a code-set interpretation."""

    CONFIRMED = "CONFIRMED"
    CANDIDATE = "CANDIDATE"
    UNMAPPED = "UNMAPPED"


JsonScalar = str | int | float | bool | None
SourceScalar = str | int | float | bool | Decimal | date | datetime | None


def _json_safe(value: Any) -> JsonScalar:
    """Return a deterministic JSON scalar without changing the stored value."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"value is not a supported typed-staging scalar: {type(value)!r}")


@dataclass(frozen=True, slots=True)
class TypedRule:
    """One occurrence-aware source-column conversion specification."""

    logical_table_id: str
    source_column: str
    declared_type: str
    observed_types: tuple[str, ...]
    target_type: TargetType
    transform_policy: TransformPolicy
    null_policy: NullPolicy = NullPolicy.PRESERVE_MISSING
    whitespace_policy: WhitespacePolicy = WhitespacePolicy.PRESERVE
    parse_failure_policy: ParseFailurePolicy = ParseFailurePolicy.RECORD_PARSE_ERROR
    unit_status: UnitStatus = UnitStatus.UNMAPPED
    code_status: CodeStatus = CodeStatus.UNMAPPED
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    occurrence: int = 1
    qualified_name: str | None = None

    def __post_init__(self) -> None:
        if not self.logical_table_id:
            raise ValueError("logical_table_id must not be empty")
        if not self.source_column:
            raise ValueError("source_column must not be empty")
        if not self.declared_type:
            raise ValueError("declared_type must not be empty")
        if isinstance(self.occurrence, bool) or self.occurrence < 1:
            raise ValueError("occurrence must be a positive integer")

        expected_name = f"{self.source_column}#{self.occurrence}"
        if self.qualified_name is None:
            object.__setattr__(self, "qualified_name", expected_name)
        elif self.qualified_name != expected_name:
            raise ValueError(
                "qualified_name must use the occurrence-aware '<column>#<n>' form"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping with enum values represented as strings."""

        return {
            "logical_table_id": self.logical_table_id,
            "source_column": self.source_column,
            "occurrence": self.occurrence,
            "qualified_name": self.qualified_name,
            "declared_type": self.declared_type,
            "observed_types": list(self.observed_types),
            "target_type": self.target_type.value,
            "transform_policy": self.transform_policy.value,
            "null_policy": self.null_policy.value,
            "whitespace_policy": self.whitespace_policy.value,
            "parse_failure_policy": self.parse_failure_policy.value,
            "unit_status": self.unit_status.value,
            "code_status": self.code_status.value,
            "mapping_status": self.mapping_status.value,
        }


@dataclass(frozen=True, slots=True)
class ParseResult:
    """A source-preserving normalized value and its explicit parse outcome."""

    raw_value: SourceScalar
    normalized_value: SourceScalar
    parse_status: ParseStatus

    def to_dict(self) -> dict[str, JsonScalar]:
        """Return a JSON-ready row result.

        Per-row results contain raw values by contract and therefore must not be
        copied into aggregate G2-A reports.
        """

        return {
            "raw_value": _json_safe(self.raw_value),
            "normalized_value": _json_safe(self.normalized_value),
            "parse_status": self.parse_status.value,
        }


__all__ = [
    "CodeStatus",
    "MappingStatus",
    "NullPolicy",
    "ParseFailurePolicy",
    "ParseResult",
    "ParseStatus",
    "SourceScalar",
    "TargetType",
    "TransformPolicy",
    "TypedRule",
    "UnitStatus",
    "WhitespacePolicy",
]
