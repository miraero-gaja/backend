"""Build source-to-concept candidates from the official schema profile.

G2-A does not define a canonical financial vocabulary. An official schema
display name is therefore retained only as a review candidate. A missing
display name remains unmapped, and this module never promotes a candidate to
``CONFIRMED``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any


CONCEPT_STATUSES = frozenset({"CANDIDATE", "UNMAPPED"})
_OFFICIAL_TABLE_IDS = frozenset(
    {"PRBD01N001", "PREF01N001", "PREF02N001", "PRFD01N001"}
)
_OFFICIAL_COLUMN_COUNT = 207


class ConceptRegistryError(ValueError):
    """Raised when a schema profile cannot form an unambiguous registry."""


def _non_blank_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _column_identity(column: Mapping[str, Any]) -> tuple[str, int, str]:
    source_column = _non_blank_text(column.get("column_name"))
    if source_column is None:
        raise ConceptRegistryError("schema column is missing column_name")

    occurrence_value = column.get("occurrence", 1)
    try:
        occurrence = int(occurrence_value)
    except (TypeError, ValueError) as exc:
        raise ConceptRegistryError(
            f"invalid occurrence for schema column {source_column!r}: "
            f"{occurrence_value!r}"
        ) from exc
    if occurrence < 1:
        raise ConceptRegistryError(
            f"occurrence must be positive for schema column {source_column!r}"
        )

    qualified_name = _non_blank_text(column.get("qualified_name"))
    if qualified_name is None:
        qualified_name = f"{source_column}#{occurrence}"
    return source_column, occurrence, qualified_name


def build_concept_registry(
    schema_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one conservative concept entry for every schema column.

    Duplicate column names are kept distinct by their occurrence-aware
    ``qualified_name``. The returned payload contains no source row values.
    """

    tables = schema_profile.get("tables")
    if not isinstance(tables, list):
        raise ConceptRegistryError("schema_profile.tables must be a list")

    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    table_counts: Counter[str] = Counter()

    for table in tables:
        if not isinstance(table, Mapping):
            raise ConceptRegistryError("each schema table must be an object")
        logical_table_id = _non_blank_text(table.get("logical_table_id"))
        if logical_table_id is None:
            raise ConceptRegistryError("schema table is missing logical_table_id")
        columns = table.get("columns")
        if not isinstance(columns, list):
            raise ConceptRegistryError(
                f"schema table {logical_table_id} columns must be a list"
            )

        for column in columns:
            if not isinstance(column, Mapping):
                raise ConceptRegistryError(
                    f"schema table {logical_table_id} contains a non-object column"
                )
            source_column, occurrence, qualified_name = _column_identity(column)
            identity = (logical_table_id, qualified_name)
            if identity in seen:
                raise ConceptRegistryError(
                    "duplicate occurrence-aware schema identity: "
                    f"{logical_table_id}.{qualified_name}"
                )
            seen.add(identity)

            display_name = _non_blank_text(column.get("display_name"))
            if display_name is None:
                concept_candidate = None
                concept_status = "UNMAPPED"
                evidence = None
                notes = (
                    "Official schema display name is missing; no concept was inferred."
                )
            else:
                concept_candidate = display_name
                concept_status = "CANDIDATE"
                evidence = "official_schema_display_name"
                notes = (
                    "Candidate label only; no canonical concept or cross-table "
                    "semantic equivalence is confirmed."
                )

            entries.append(
                {
                    "logical_table_id": logical_table_id,
                    "source_column": source_column,
                    "occurrence": occurrence,
                    "qualified_name": qualified_name,
                    "schema_display_name": display_name,
                    "concept_candidate": concept_candidate,
                    "concept_status": concept_status,
                    "evidence": evidence,
                    "notes": notes,
                }
            )
            table_counts[logical_table_id] += 1

    status_counts = Counter(entry["concept_status"] for entry in entries)
    registry = {
        "registry_format_version": "1.0",
        "policy": {
            "canonical_vocabulary_present": False,
            "official_display_name_treatment": "CANDIDATE_ONLY",
            "missing_display_name_treatment": "UNMAPPED",
            "semantic_unification_performed": False,
        },
        "entries": entries,
        "summary": {
            "entry_count": len(entries),
            "table_column_counts": dict(table_counts),
            "status_counts": {
                status: status_counts.get(status, 0)
                for status in ("CONFIRMED", "CANDIDATE", "UNMAPPED")
            },
        },
    }
    expected_count = (
        _OFFICIAL_COLUMN_COUNT
        if set(table_counts) == _OFFICIAL_TABLE_IDS
        else len(entries)
    )
    registry["validation"] = validate_concept_registry(
        registry, expected_column_count=expected_count
    )
    return registry


def concept_entries_by_source(
    registry: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index registry entries by ``(logical_table_id, qualified_name)``."""

    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise ConceptRegistryError("concept registry entries must be a list")

    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ConceptRegistryError("concept registry entry must be an object")
        logical_table_id = _non_blank_text(entry.get("logical_table_id"))
        qualified_name = _non_blank_text(entry.get("qualified_name"))
        if logical_table_id is None or qualified_name is None:
            raise ConceptRegistryError(
                "concept entry requires logical_table_id and qualified_name"
            )
        identity = (logical_table_id, qualified_name)
        if identity in indexed:
            raise ConceptRegistryError(
                f"duplicate concept entry: {logical_table_id}.{qualified_name}"
            )
        indexed[identity] = entry
    return indexed


def validate_concept_registry(
    registry: Mapping[str, Any],
    *,
    expected_column_count: int | None = None,
) -> dict[str, Any]:
    """Validate identity uniqueness, status values, and optional row count."""

    indexed = concept_entries_by_source(registry)
    entries = registry.get("entries", [])
    invalid_status_entries = [
        f"{entry.get('logical_table_id')}.{entry.get('qualified_name')}"
        for entry in entries
        if entry.get("concept_status") not in CONCEPT_STATUSES
    ]
    confirmed_entries = [
        f"{entry.get('logical_table_id')}.{entry.get('qualified_name')}"
        for entry in entries
        if entry.get("concept_status") == "CONFIRMED"
    ]
    count_matches = (
        expected_column_count is None or len(entries) == expected_column_count
    )
    is_valid = (
        len(indexed) == len(entries)
        and not invalid_status_entries
        and not confirmed_entries
        and count_matches
    )
    return {
        "entry_count": len(entries),
        "unique_source_occurrence_count": len(indexed),
        "expected_column_count": expected_column_count,
        "expected_column_count_match": count_matches,
        "duplicate_occurrence_aware": True,
        "invalid_status_entries": invalid_status_entries,
        "confirmed_without_canonical_vocabulary": confirmed_entries,
        "is_valid": is_valid,
    }
