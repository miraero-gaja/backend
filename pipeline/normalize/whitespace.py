"""Aggregate-only whitespace impact analysis.

No source value, normalized value, or value digest is exposed by this module.
It evaluates a hypothetical ``str.strip()`` policy without applying that policy
to typed staging values.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .models import SourceScalar


class TrimStatus(StrEnum):
    """Safety status of a hypothetical whitespace trim."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    SAFE = "SAFE"
    CONFLICT = "CONFLICT"


def _typed_payload(value: SourceScalar) -> bytes:
    if isinstance(value, str):
        tag, payload = b"str", value.encode("utf-8")
    elif isinstance(value, bool):
        tag, payload = b"bool", b"1" if value else b"0"
    elif isinstance(value, int):
        tag, payload = b"int", str(value).encode("ascii")
    elif isinstance(value, float):
        tag, payload = b"float", value.hex().encode("ascii")
    elif isinstance(value, Decimal):
        tag, payload = b"decimal", str(value).encode("ascii")
    elif isinstance(value, datetime):
        tag, payload = b"datetime", value.isoformat().encode("ascii")
    elif isinstance(value, date):
        tag, payload = b"date", value.isoformat().encode("ascii")
    else:
        raise TypeError(f"unsupported whitespace-analysis value: {type(value)!r}")
    return tag + len(payload).to_bytes(8, "big") + payload


def _digest(value: SourceScalar) -> bytes:
    return hashlib.sha256(_typed_payload(value)).digest()


@dataclass(frozen=True, slots=True)
class WhitespaceAnalysis:
    """Non-identifying aggregate result for one source-column occurrence."""

    total_count: int
    missing_count: int
    empty_string_count: int
    null_class_count: int
    present_count: int
    string_count: int
    trimmed_value_count: int
    whitespace_only_count: int
    distinct_count_before_trim: int
    distinct_count_after_trim: int
    collapsed_distinct_count: int
    collision_group_count: int
    trim_collision_detected: bool
    trim_status: TrimStatus
    identifier_assessed: bool
    identifier_unique_before_trim: bool | None
    identifier_unique_after_trim: bool | None
    identifier_uniqueness_changed: bool | None

    @property
    def before_distinct_count(self) -> int:
        """Compatibility alias with the before/after wording in the spec."""

        return self.distinct_count_before_trim

    @property
    def after_distinct_count(self) -> int:
        return self.distinct_count_after_trim

    @property
    def collision_detected(self) -> bool:
        return self.trim_collision_detected

    def to_dict(self) -> dict[str, Any]:
        """Return aggregate JSON data; raw values and digests are never included."""

        return {
            "total_count": self.total_count,
            "missing_count": self.missing_count,
            "empty_string_count": self.empty_string_count,
            "null_class_count": self.null_class_count,
            "present_count": self.present_count,
            "string_count": self.string_count,
            "trimmed_value_count": self.trimmed_value_count,
            "whitespace_only_count": self.whitespace_only_count,
            "distinct_count_before_trim": self.distinct_count_before_trim,
            "distinct_count_after_trim": self.distinct_count_after_trim,
            "collapsed_distinct_count": self.collapsed_distinct_count,
            "collision_group_count": self.collision_group_count,
            "trim_collision_detected": self.trim_collision_detected,
            "trim_status": self.trim_status.value,
            "identifier_assessed": self.identifier_assessed,
            "identifier_unique_before_trim": self.identifier_unique_before_trim,
            "identifier_unique_after_trim": self.identifier_unique_after_trim,
            "identifier_uniqueness_changed": self.identifier_uniqueness_changed,
        }


def analyze_trim_impact(
    values: Iterable[SourceScalar],
    *,
    identifier: bool = False,
) -> WhitespaceAnalysis:
    """Measure hypothetical trim collisions without returning source values.

    Identifier uniqueness requires every row to be nonblank as well as unique.
    Missing, exact-empty, and whitespace-only values are therefore explicit
    blockers rather than being hidden by a present-value-only distinct count.
    """

    total_count = 0
    missing_count = 0
    empty_string_count = 0
    string_count = 0
    trimmed_value_count = 0
    whitespace_only_count = 0
    before_digests: set[bytes] = set()
    after_groups: dict[bytes, set[bytes]] = defaultdict(set)

    for value in values:
        total_count += 1
        if value is None:
            missing_count += 1
            continue

        before = _digest(value)
        before_digests.add(before)
        after_value = value
        if isinstance(value, str):
            string_count += 1
            if value == "":
                empty_string_count += 1
            stripped = value.strip()
            if stripped != value:
                trimmed_value_count += 1
            if value != "" and value.isspace():
                whitespace_only_count += 1
            after_value = stripped
        after_groups[_digest(after_value)].add(before)

    present_count = total_count - missing_count
    null_class_count = (
        missing_count + empty_string_count + whitespace_only_count
    )
    distinct_before = len(before_digests)
    distinct_after = len(after_groups)
    collision_group_count = sum(
        1 for source_digests in after_groups.values() if len(source_digests) > 1
    )
    collision_detected = collision_group_count > 0
    if collision_detected:
        trim_status = TrimStatus.CONFLICT
    elif trimmed_value_count:
        trim_status = TrimStatus.SAFE
    else:
        trim_status = TrimStatus.NOT_APPLICABLE

    if identifier:
        unique_before = (
            total_count > 0
            and null_class_count == 0
            and distinct_before == total_count
        )
        unique_after = (
            total_count > 0
            and null_class_count == 0
            and distinct_after == total_count
        )
        uniqueness_changed: bool | None = unique_before != unique_after
    else:
        unique_before = None
        unique_after = None
        uniqueness_changed = None

    return WhitespaceAnalysis(
        total_count=total_count,
        missing_count=missing_count,
        empty_string_count=empty_string_count,
        null_class_count=null_class_count,
        present_count=present_count,
        string_count=string_count,
        trimmed_value_count=trimmed_value_count,
        whitespace_only_count=whitespace_only_count,
        distinct_count_before_trim=distinct_before,
        distinct_count_after_trim=distinct_after,
        collapsed_distinct_count=distinct_before - distinct_after,
        collision_group_count=collision_group_count,
        trim_collision_detected=collision_detected,
        trim_status=trim_status,
        identifier_assessed=identifier,
        identifier_unique_before_trim=unique_before,
        identifier_unique_after_trim=unique_after,
        identifier_uniqueness_changed=uniqueness_changed,
    )


def analyze_whitespace(
    values: Iterable[SourceScalar],
    *,
    identifier: bool = False,
) -> WhitespaceAnalysis:
    """Alias using the broader G2-A policy terminology."""

    return analyze_trim_impact(values, identifier=identifier)


__all__ = [
    "TrimStatus",
    "WhitespaceAnalysis",
    "analyze_trim_impact",
    "analyze_whitespace",
]
