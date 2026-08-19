"""Build the occurrence-aware G2-A coverage matrix.

The registry joins G1 schema and data profiles without reading or copying raw
rows. Typed, parse, and whitespace aggregate evidence may be supplied by the
normalization pipeline. Operations are advertised only when a target type is
confirmed and zero parse failures are evidenced.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from mappings.concepts.registry import (
    ConceptRegistryError,
    build_concept_registry,
    concept_entries_by_source,
)


OFFICIAL_EXPECTED_COLUMN_COUNT = 207
OFFICIAL_TABLE_IDS = frozenset(
    {"PRBD01N001", "PREF01N001", "PREF02N001", "PRFD01N001"}
)
TYPED_STATUSES = frozenset(
    {"READY", "PARSE_REVIEW_REQUIRED", "UNSUPPORTED", "UNASSESSED"}
)

_TEXT_TARGETS = frozenset({"TEXT", "STRING"})
_INTEGER_TARGETS = frozenset({"INTEGER", "BIGINT", "INT"})
_DECIMAL_TARGETS = frozenset({"DECIMAL", "NUMERIC"})
_DATE_TARGETS = frozenset({"DATE"})
_TIMESTAMP_TARGETS = frozenset({"TIMESTAMP", "DATETIME"})
_BOOLEAN_TARGETS = frozenset({"BOOLEAN", "BOOL"})


class CoverageRegistryError(ValueError):
    """Raised when source coverage is ambiguous or incomplete."""


def _plain_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        result = model_dump(mode="json")
        if isinstance(result, Mapping):
            return dict(result)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise CoverageRegistryError(f"unsupported evidence record: {type(value)!r}")


def _non_blank_text(value: Any) -> str | None:
    value = _plain_value(value)
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _qualified_name(record: Mapping[str, Any]) -> str | None:
    qualified = _non_blank_text(record.get("qualified_name"))
    if qualified is not None:
        return qualified
    source = _non_blank_text(
        record.get("source_column", record.get("column_name"))
    )
    if source is None:
        return None
    occurrence = record.get("occurrence", 1)
    try:
        occurrence_int = int(occurrence)
    except (TypeError, ValueError) as exc:
        raise CoverageRegistryError(
            f"invalid occurrence for evidence column {source!r}: {occurrence!r}"
        ) from exc
    return f"{source}#{occurrence_int}"


def _iter_records(payload: Any) -> Iterable[dict[str, Any]]:
    """Yield records from report/list/dataclass shapes used by G2-A."""

    if payload is None:
        return
    if isinstance(payload, Mapping):
        if (
            "logical_table_id" in payload
            and ("source_column" in payload or "column_name" in payload)
        ):
            yield dict(payload)
            return

        for container_key in (
            "rules",
            "entries",
            "columns",
            "aggregates",
            "results",
        ):
            contained = payload.get(container_key)
            if isinstance(contained, (list, tuple)):
                for value in contained:
                    yield from _iter_records(value)
                return

        tables = payload.get("tables")
        if isinstance(tables, list):
            for table in tables:
                table_record = _record(table)
                table_id = _non_blank_text(table_record.get("logical_table_id"))
                nested = None
                for key in (
                    "rules",
                    "entries",
                    "columns",
                    "aggregates",
                    "results",
                ):
                    if isinstance(table_record.get(key), list):
                        nested = table_record[key]
                        break
                if nested is None:
                    continue
                for value in nested:
                    child = _record(value)
                    if table_id is not None:
                        child.setdefault("logical_table_id", table_id)
                    yield child
            return

        for key, value in payload.items():
            if key in {"summary", "validation", "policy", "metadata"}:
                continue
            if isinstance(value, (list, tuple)):
                for child_value in value:
                    child = _record(child_value)
                    if isinstance(key, str) and key in OFFICIAL_TABLE_IDS:
                        child.setdefault("logical_table_id", key)
                    yield from _iter_records(child)
                continue
            if not isinstance(value, Mapping) and not is_dataclass(value):
                continue
            child = _record(value)
            if isinstance(key, tuple) and len(key) == 2:
                child.setdefault("logical_table_id", key[0])
                child.setdefault("qualified_name", key[1])
            elif isinstance(key, str) and key in OFFICIAL_TABLE_IDS:
                child.setdefault("logical_table_id", key)
            yield from _iter_records(child)
        return

    if isinstance(payload, (list, tuple)):
        for value in payload:
            yield from _iter_records(value)
        return

    yield _record(payload)


def _index_records(
    payload: Any,
    *,
    label: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for record in _iter_records(payload):
        table_id = _non_blank_text(record.get("logical_table_id"))
        qualified = _qualified_name(record)
        if table_id is None or qualified is None:
            raise CoverageRegistryError(
                f"{label} record requires logical_table_id and source column identity"
            )
        identity = (table_id, qualified)
        if identity in indexed:
            raise CoverageRegistryError(
                f"duplicate {label} record: {table_id}.{qualified}"
            )
        indexed[identity] = record
    return indexed


def _profile_columns(
    profile: Mapping[str, Any],
    *,
    profile_name: str,
) -> tuple[list[tuple[str, str]], dict[tuple[str, str], Mapping[str, Any]]]:
    tables = profile.get("tables")
    if not isinstance(tables, list):
        raise CoverageRegistryError(f"{profile_name}.tables must be a list")

    ordered: list[tuple[str, str]] = []
    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for table in tables:
        if not isinstance(table, Mapping):
            raise CoverageRegistryError(f"{profile_name} table must be an object")
        table_id = _non_blank_text(table.get("logical_table_id"))
        if table_id is None:
            raise CoverageRegistryError(
                f"{profile_name} table is missing logical_table_id"
            )
        columns = table.get("columns")
        if not isinstance(columns, list):
            raise CoverageRegistryError(
                f"{profile_name} table {table_id} columns must be a list"
            )
        for column in columns:
            if not isinstance(column, Mapping):
                raise CoverageRegistryError(
                    f"{profile_name} table {table_id} contains non-object column"
                )
            qualified = _qualified_name(column)
            if qualified is None:
                raise CoverageRegistryError(
                    f"{profile_name} table {table_id} column identity is missing"
                )
            identity = (table_id, qualified)
            if identity in indexed:
                raise CoverageRegistryError(
                    f"duplicate {profile_name} identity: {table_id}.{qualified}"
                )
            ordered.append(identity)
            indexed[identity] = column
    return ordered, indexed


def _status(record: Mapping[str, Any] | None, *keys: str, default: str) -> str:
    if record is None:
        return default
    for key in keys:
        value = _non_blank_text(record.get(key))
        if value is not None:
            return value.upper()
    return default


def _parse_error_evidence(
    parse_record: Mapping[str, Any] | None,
    typed_rule: Mapping[str, Any] | None,
) -> tuple[int | None, str]:
    for record, source in (
        (parse_record, "parse_aggregate"),
        (typed_rule, "typed_rule"),
    ):
        if record is None:
            continue
        value = record.get("parse_error_count")
        if value is None and isinstance(record.get("status_counts"), Mapping):
            value = record["status_counts"].get("PARSE_ERROR")
        if value is None:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise CoverageRegistryError(
                f"parse_error_count must be an integer, got {value!r}"
            ) from exc
        if count < 0:
            raise CoverageRegistryError("parse_error_count cannot be negative")
        return count, source
    return None, "not_supplied"


def _safe_operations(
    *,
    typed_status: str,
    target_type: str | None,
    parse_error_count: int | None,
    code_status: str,
    concept_status: str,
    unit_status: str,
) -> list[str]:
    if typed_status != "READY" or target_type is None:
        return []
    if parse_error_count is None or parse_error_count != 0:
        return []

    normalized_target = target_type.upper()
    if normalized_target in _BOOLEAN_TARGETS:
        return ["EQ", "NE"]
    if code_status in {"CONFIRMED", "CANDIDATE"}:
        return ["EQ", "NE"]
    if normalized_target in _TEXT_TARGETS:
        return ["EQ", "NE", "TEXT_MATCH"]
    if normalized_target in _INTEGER_TARGETS | _DECIMAL_TARGETS:
        operations = ["EQ", "NE", "LT", "LE", "GT", "GE", "SORT"]
        if concept_status == "CONFIRMED" and unit_status == "CONFIRMED":
            operations.append("AGGREGATE")
        return operations
    if normalized_target in _DATE_TARGETS | _TIMESTAMP_TARGETS:
        return ["EQ", "NE", "LT", "LE", "GT", "GE", "SORT"]
    return []


def _typed_status(
    typed_rule: Mapping[str, Any] | None,
    target_type: str | None,
    parse_error_count: int | None,
) -> str:
    """Derive technical readiness independently from concept mapping status."""

    if typed_rule is None or target_type is None:
        return "UNASSESSED"
    supported_targets = (
        _TEXT_TARGETS
        | _INTEGER_TARGETS
        | _DECIMAL_TARGETS
        | _DATE_TARGETS
        | _TIMESTAMP_TARGETS
        | _BOOLEAN_TARGETS
    )
    if target_type.upper() not in supported_targets:
        return "UNSUPPORTED"
    if parse_error_count == 0:
        return "READY"
    return "PARSE_REVIEW_REQUIRED"


def _identifier_role(
    data_column: Mapping[str, Any],
    candidate_names: set[str],
) -> str:
    qualified = _qualified_name(data_column)
    is_declared = bool(data_column.get("declared_primary_key"))
    is_candidate = qualified in candidate_names
    if is_declared and is_candidate:
        return "DECLARED_KEY_COMPONENT_AND_CANDIDATE"
    if is_declared:
        return "DECLARED_KEY_COMPONENT"
    if is_candidate:
        return "CANDIDATE_IDENTIFIER"
    return "NONE"


def _candidate_identifier_names(table: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    candidates = table.get("candidate_identifiers", [])
    if not isinstance(candidates, list):
        return names
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        qualified = _qualified_name(candidate)
        if qualified is not None:
            names.add(qualified)
    return names


def build_coverage_registry(
    schema_profile: Mapping[str, Any],
    data_profile: Mapping[str, Any],
    *,
    typed_rules: Any = None,
    parse_aggregates: Any = None,
    whitespace_aggregates: Any = None,
    expected_column_count: int | None = None,
) -> dict[str, Any]:
    """Build one coverage entry per actual G1 data column.

    Schema and data identities must match exactly. Optional evidence is joined
    by ``logical_table_id`` plus occurrence-aware ``qualified_name``.
    """

    schema_order, schema_columns = _profile_columns(
        schema_profile, profile_name="schema_profile"
    )
    data_order, data_columns = _profile_columns(
        data_profile, profile_name="data_profile"
    )
    schema_ids = set(schema_columns)
    data_ids = set(data_columns)
    if schema_ids != data_ids:
        missing = sorted(f"{table}.{column}" for table, column in data_ids - schema_ids)
        extra = sorted(f"{table}.{column}" for table, column in schema_ids - data_ids)
        raise CoverageRegistryError(
            f"schema/data column identities differ; schema_missing={missing}, "
            f"schema_only={extra}"
        )
    if schema_order != data_order:
        raise CoverageRegistryError("schema/data column order differs")

    concept_registry = build_concept_registry(schema_profile)
    try:
        concepts = concept_entries_by_source(concept_registry)
    except ConceptRegistryError as exc:
        raise CoverageRegistryError(str(exc)) from exc

    typed_index = _index_records(typed_rules, label="typed rule")
    parse_index = _index_records(parse_aggregates, label="parse aggregate")
    whitespace_index = _index_records(
        whitespace_aggregates, label="whitespace aggregate"
    )

    data_tables = {
        str(table["logical_table_id"]): table
        for table in data_profile.get("tables", [])
    }
    candidate_names_by_table = {
        table_id: _candidate_identifier_names(table)
        for table_id, table in data_tables.items()
    }

    entries: list[dict[str, Any]] = []
    table_counts: Counter[str] = Counter()
    for identity in data_order:
        table_id, qualified_name = identity
        schema_column = schema_columns[identity]
        data_column = data_columns[identity]
        concept = concepts[identity]
        typed_rule = typed_index.get(identity)
        parse_record = parse_index.get(identity)
        whitespace_record = whitespace_index.get(identity)

        source_column = _non_blank_text(data_column.get("column_name"))
        if source_column is None:
            raise CoverageRegistryError(
                f"data column name missing for {table_id}.{qualified_name}"
            )
        occurrence = int(data_column.get("occurrence", 1))
        row_count = int(data_column.get("row_count", 0))
        non_null_count = int(data_column.get("non_null_count", 0))
        non_null_ratio = (
            round(non_null_count / row_count, 8) if row_count > 0 else 0.0
        )

        target_type = (
            _non_blank_text(typed_rule.get("target_type"))
            if typed_rule is not None
            else None
        )
        if target_type is not None:
            target_type = target_type.upper()
        parse_error_count, parse_evidence = _parse_error_evidence(
            parse_record, typed_rule
        )
        typed_status = _typed_status(
            typed_rule, target_type, parse_error_count
        )

        unit_status = _status(
            typed_rule,
            "unit_status",
            default=(
                "CONFIRMED"
                if _non_blank_text(schema_column.get("declared_unit")) is not None
                else "UNMAPPED"
            ),
        )
        code_status = _status(typed_rule, "code_status", default="UNMAPPED")
        if code_status == "UNMAPPED" and (
            bool(data_column.get("enum_code_candidate"))
            or bool(data_column.get("boolean_code_candidate"))
            or bool(
                isinstance(data_column.get("code_like_string"), Mapping)
                and data_column["code_like_string"].get("candidate")
            )
        ):
            code_status = "CANDIDATE"

        supported_operations = _safe_operations(
            typed_status=typed_status,
            target_type=target_type,
            parse_error_count=parse_error_count,
            code_status=code_status,
            concept_status=str(concept["concept_status"]),
            unit_status=unit_status,
        )
        identifier_role = _identifier_role(
            data_column, candidate_names_by_table.get(table_id, set())
        )
        note_parts = [
            "Coverage is occurrence-aware and based on the G1 schema/data profiles."
        ]
        if identifier_role.startswith("DECLARED_KEY_COMPONENT") and non_null_ratio < 1.0:
            note_parts.append(
                "Declared key component contains missing/empty/whitespace-only "
                "values and is not asserted as an enforceable business primary key."
            )
        if typed_status == "UNASSESSED":
            note_parts.append("No typed rule was supplied; operations are disabled.")
        elif typed_status == "UNSUPPORTED":
            note_parts.append("Target type is unsupported; operations are disabled.")
        elif parse_error_count is None:
            note_parts.append(
                "Parse-error aggregate evidence is absent; operations are disabled."
            )
        elif parse_error_count > 0:
            note_parts.append(
                "Parse errors were observed; operations are disabled pending review."
            )
        if whitespace_record is not None:
            collision_count = whitespace_record.get(
                "trim_collision_count",
                whitespace_record.get("collision_group_count"),
            )
            collision_detected = whitespace_record.get("trim_collision_detected")
            uniqueness_changed = whitespace_record.get(
                "identifier_uniqueness_changed"
            )
            if collision_count not in (None, 0, "0") or collision_detected is True:
                note_parts.append("Trim collision evidence requires manual review.")
            if uniqueness_changed is True:
                note_parts.append("Trim changes identifier uniqueness.")

        entries.append(
            {
                "logical_table_id": table_id,
                "source_column": source_column,
                "occurrence": occurrence,
                "qualified_name": qualified_name,
                "declared_type": schema_column.get("declared_type"),
                "non_null_ratio": non_null_ratio,
                "identifier_role": identifier_role,
                "typed_status": typed_status,
                "target_type": target_type,
                "concept_candidate": concept["concept_candidate"],
                "concept_status": concept["concept_status"],
                "unit_status": unit_status,
                "code_status": code_status,
                "supported_operations": supported_operations,
                "parse_error_count": parse_error_count,
                "parse_error_evidence": parse_evidence,
                "notes": " ".join(note_parts),
            }
        )
        table_counts[table_id] += 1

    official_dataset = set(table_counts) == OFFICIAL_TABLE_IDS
    resolved_expected_count = expected_column_count
    if resolved_expected_count is None:
        resolved_expected_count = (
            OFFICIAL_EXPECTED_COLUMN_COUNT if official_dataset else len(data_order)
        )

    typed_counts = Counter(entry["typed_status"] for entry in entries)
    concept_counts = Counter(entry["concept_status"] for entry in entries)
    unit_counts = Counter(entry["unit_status"] for entry in entries)
    code_counts = Counter(entry["code_status"] for entry in entries)
    operation_counts = Counter(
        operation for entry in entries for operation in entry["supported_operations"]
    )

    registry = {
        "registry_format_version": "1.0",
        "coverage_basis": {
            "source": "G1 schema/data profiles plus optional G2-A aggregates",
            "source_rows_copied": False,
            "duplicate_occurrence_aware": True,
            "operation_policy": (
                "Operations require a supported target type and explicit zero "
                "parse-error evidence; AGGREGATE additionally requires confirmed "
                "concept and unit evidence."
            ),
        },
        "entries": entries,
        "summary": {
            "actual_column_count": len(data_order),
            "registry_entry_count": len(entries),
            "covered_column_count": len(entries),
            "coverage_ratio": round(len(entries) / len(data_order), 8)
            if data_order
            else 1.0,
            "table_column_counts": dict(table_counts),
            "typed_status_counts": {
                status: typed_counts.get(status, 0)
                for status in (
                    "READY",
                    "PARSE_REVIEW_REQUIRED",
                    "UNSUPPORTED",
                    "UNASSESSED",
                )
            },
            "concept_status_counts": {
                status: concept_counts.get(status, 0)
                for status in ("CONFIRMED", "CANDIDATE", "UNMAPPED")
            },
            "unit_status_counts": {
                status: unit_counts.get(status, 0)
                for status in ("CONFIRMED", "CANDIDATE", "UNMAPPED")
            },
            "code_status_counts": {
                status: code_counts.get(status, 0)
                for status in ("CONFIRMED", "CANDIDATE", "UNMAPPED")
            },
            "supported_operation_counts": dict(sorted(operation_counts.items())),
        },
    }
    registry["validation"] = validate_coverage_registry(
        registry,
        expected_column_count=resolved_expected_count,
        actual_source_identities=data_order,
    )
    return registry


def validate_coverage_registry(
    registry: Mapping[str, Any],
    *,
    expected_column_count: int = OFFICIAL_EXPECTED_COLUMN_COUNT,
    actual_source_identities: Iterable[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate exact occurrence-aware source coverage and official count."""

    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise CoverageRegistryError("coverage registry entries must be a list")

    identities: list[tuple[str, str]] = []
    missing_required_fields: list[str] = []
    required_fields = {
        "logical_table_id",
        "source_column",
        "declared_type",
        "non_null_ratio",
        "identifier_role",
        "typed_status",
        "concept_candidate",
        "concept_status",
        "unit_status",
        "code_status",
        "supported_operations",
        "notes",
    }
    invalid_operations: list[str] = []
    invalid_typed_status_entries: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise CoverageRegistryError(f"coverage entry {index} must be an object")
        absent = sorted(required_fields - set(entry))
        if absent:
            missing_required_fields.append(f"entry[{index}]: {', '.join(absent)}")
        table_id = _non_blank_text(entry.get("logical_table_id"))
        qualified = _qualified_name(entry)
        if table_id is None or qualified is None:
            missing_required_fields.append(f"entry[{index}]: source identity")
            continue
        identities.append((table_id, qualified))
        typed_status = entry.get("typed_status")
        if typed_status not in TYPED_STATUSES:
            invalid_typed_status_entries.append(f"{table_id}.{qualified}")
        target_type = _non_blank_text(entry.get("target_type"))
        expected_operations = _safe_operations(
            typed_status=str(typed_status),
            target_type=target_type,
            parse_error_count=entry.get("parse_error_count"),
            code_status=str(entry.get("code_status")),
            concept_status=str(entry.get("concept_status")),
            unit_status=str(entry.get("unit_status")),
        )
        if entry.get("supported_operations") != expected_operations:
            invalid_operations.append(f"{table_id}.{qualified}")

    identity_counts = Counter(identities)
    duplicate_identities = sorted(
        f"{table}.{column}"
        for (table, column), count in identity_counts.items()
        if count > 1
    )
    registry_ids = set(identities)
    actual_ids = (
        set(actual_source_identities)
        if actual_source_identities is not None
        else registry_ids
    )
    missing_actual_columns = sorted(
        f"{table}.{column}" for table, column in actual_ids - registry_ids
    )
    unexpected_registry_columns = sorted(
        f"{table}.{column}" for table, column in registry_ids - actual_ids
    )
    exact_source_coverage = (
        not duplicate_identities
        and not missing_actual_columns
        and not unexpected_registry_columns
        and len(entries) == len(actual_ids)
    )
    expected_count_match = len(entries) == expected_column_count
    is_valid = (
        exact_source_coverage
        and expected_count_match
        and not missing_required_fields
        and not invalid_typed_status_entries
        and not invalid_operations
    )
    return {
        "expected_column_count": expected_column_count,
        "actual_source_column_count": len(actual_ids),
        "registry_entry_count": len(entries),
        "unique_source_occurrence_count": len(registry_ids),
        "expected_column_count_match": expected_count_match,
        "exact_source_coverage": exact_source_coverage,
        "coverage_ratio": round(len(registry_ids & actual_ids) / len(actual_ids), 8)
        if actual_ids
        else 1.0,
        "duplicate_occurrence_aware": True,
        "duplicate_identities": duplicate_identities,
        "missing_actual_columns": missing_actual_columns,
        "unexpected_registry_columns": unexpected_registry_columns,
        "missing_required_fields": missing_required_fields,
        "invalid_typed_status_entries": invalid_typed_status_entries,
        "unsafe_operation_entries": invalid_operations,
        "is_valid": is_valid,
    }
