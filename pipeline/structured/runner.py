"""G2-B orchestration for offline validation and optional PostgreSQL loading.

The default path performs a complete read-only pass over the four official
data workbooks.  PostgreSQL is touched only when ``execute_database`` is
explicitly enabled and either an injected connection or ``DATABASE_URL``
value is supplied by the caller.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.structured import (
    AggregateFunction,
    FilterOperator,
    SortDirection,
    StructuredFilter,
    StructuredQueryCompiler,
    StructuredQueryContract,
    StructuredSort,
    build_trusted_query_registry,
)
from mappings.core import (
    CORE_FIELD_MAPPINGS,
    CoreFieldMapping,
    build_core_field_registry,
    get_confirmed_core_fields,
)
from pipeline.normalize.constants import G2A_REPORT_FILENAMES
from pipeline.normalize.models import TargetType, TypedRule
from pipeline.normalize.scanner import build_rules_from_profiles
from pipeline.profiling.constants import EXPECTED_TOTAL_ROWS, REPORT_FILENAMES, TABLE_SPECS
from pipeline.profiling.discovery import (
    SourceWorkbook,
    discover_workbooks,
    sha256_file,
    verify_sources_unchanged,
)

from .loader import ConnectionLike, iter_typed_rows, load_all
from .reports import G2B_REPORT_FILENAMES, write_g2b_reports
from .schema import (
    OFFICIAL_STAGING_COLUMN_COUNTS,
    OFFICIAL_STAGING_COLUMN_TOTAL,
    StagingSchemaSpec,
    build_staging_schema,
)


G2B_FORMAT_VERSION = "1.0"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class G2BRunnerError(ValueError):
    """Raised when official inputs or a G2-B invariant fail closed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def _resolve_directory(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise G2BRunnerError(f"{label} is not a directory: {resolved}")
    return resolved


def _validate_output_directory(
    output_dir: str | Path,
    *,
    protected_directories: Iterable[Path],
) -> Path:
    output = Path(output_dir).expanduser().resolve()
    protected = {_REPOSITORY_ROOT, *(path.resolve() for path in protected_directories)}
    if any(_is_within(output, directory) for directory in protected):
        raise G2BRunnerError(
            "output_dir must be outside the repository and input directories"
        )
    if any(_is_within(directory, output) for directory in protected):
        raise G2BRunnerError(
            "output_dir must not contain the repository or an input directory"
        )
    return output


def _fingerprint_files(paths: Iterable[Path]) -> dict[Path, tuple[int, int, str]]:
    return {
        path: (path.stat().st_size, path.stat().st_mtime_ns, sha256_file(path))
        for path in paths
    }


def _fingerprints_unchanged(
    fingerprints: Mapping[Path, tuple[int, int, str]],
) -> bool:
    for path, expected in fingerprints.items():
        if not path.is_file():
            return False
        stat = path.stat()
        observed = (stat.st_size, stat.st_mtime_ns, sha256_file(path))
        if observed != expected:
            return False
    return True


def _load_report_set(
    directory: Path,
    *,
    filenames: Sequence[str],
    label: str,
) -> tuple[dict[str, dict[str, Any]], tuple[Path, ...]]:
    entries = sorted(path.name for path in directory.iterdir())
    expected = sorted(filenames)
    if entries != expected:
        missing = sorted(set(expected) - set(entries))
        unexpected = sorted(set(entries) - set(expected))
        raise G2BRunnerError(
            f"{label} must contain exactly its declared artifacts; "
            f"missing={missing}, unexpected={unexpected}"
        )
    paths = tuple(directory / filename for filename in filenames)
    if not all(path.is_file() for path in paths):
        raise G2BRunnerError(f"every {label} artifact must be a regular file")

    documents: dict[str, dict[str, Any]] = {}
    for path in paths:
        if path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise G2BRunnerError(
                f"cannot read valid UTF-8 JSON from {label}: {path.name}"
            ) from error
        if not isinstance(payload, dict):
            raise G2BRunnerError(f"{label} JSON must be an object: {path.name}")
        documents[path.name] = payload
    return documents, paths


def _table_index(
    document: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    tables = document.get("tables")
    if not isinstance(tables, list):
        raise G2BRunnerError(f"{label}.tables must be a list")
    indexed: dict[str, Mapping[str, Any]] = {}
    for table in tables:
        if not isinstance(table, Mapping):
            raise G2BRunnerError(f"{label} table must be an object")
        table_id = str(table.get("logical_table_id", ""))
        if table_id not in TABLE_SPECS or table_id in indexed:
            raise G2BRunnerError(f"invalid or duplicate {label} table: {table_id!r}")
        indexed[table_id] = table
    if list(indexed) != list(TABLE_SPECS):
        raise G2BRunnerError(f"{label} table order or identities are not official")
    return indexed


def _validate_g1(
    documents: Mapping[str, Mapping[str, Any]],
    sources: tuple[SourceWorkbook, ...],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    manifest = documents["g1_file_manifest.json"]
    schema_profile = documents["g1_schema_profile.json"]
    data_profile = documents["g1_data_profile.json"]
    schema_diff = documents["g1_schema_diff.json"]
    if manifest.get("g1_data_status") != "PASS":
        raise G2BRunnerError("G1 manifest status is not PASS")
    if manifest.get("sources_immutable") is not True:
        raise G2BRunnerError("G1 did not confirm source immutability")
    if int(manifest.get("observed_total_rows", -1)) != EXPECTED_TOTAL_ROWS:
        raise G2BRunnerError("G1 total row count is not the official total")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise G2BRunnerError("G1 manifest files must be a list")
    manifest_by_identity: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise G2BRunnerError("G1 manifest file entry must be an object")
        identity = (str(entry.get("logical_table_id")), str(entry.get("source_kind")))
        if identity in manifest_by_identity:
            raise G2BRunnerError(f"duplicate G1 manifest source: {identity}")
        manifest_by_identity[identity] = entry
    source_identities = {
        (source.logical_table_id, source.source_kind) for source in sources
    }
    if set(manifest_by_identity) != source_identities:
        raise G2BRunnerError("G1 manifest identities do not match source discovery")
    for source in sources:
        entry = manifest_by_identity[(source.logical_table_id, source.source_kind)]
        expected_fields = {
            "physical_filename": source.physical_filename,
            "extension": source.extension,
            "size_bytes": source.size_bytes,
            "modified_at_utc": source.modified_at_utc,
            "sha256": source.sha256,
            "source_immutable": True,
        }
        for field, expected in expected_fields.items():
            if entry.get(field) != expected:
                raise G2BRunnerError(
                    f"G1 manifest mismatch for {source.logical_table_id}/"
                    f"{source.source_kind}: {field}"
                )

    schema_tables = _table_index(schema_profile, label="g1_schema_profile")
    data_tables = _table_index(data_profile, label="g1_data_profile")
    diff_tables = _table_index(schema_diff, label="g1_schema_diff")
    observed_rows = 0
    observed_columns = 0
    for table_id, table_spec in TABLE_SPECS.items():
        schema_columns = schema_tables[table_id].get("columns")
        data_columns = data_tables[table_id].get("columns")
        if not isinstance(schema_columns, list) or not isinstance(data_columns, list):
            raise G2BRunnerError(f"G1 columns are missing for {table_id}")
        schema_ids = [column.get("qualified_name") for column in schema_columns]
        data_ids = [column.get("qualified_name") for column in data_columns]
        if schema_ids != data_ids:
            raise G2BRunnerError(f"G1 schema/data column order differs for {table_id}")
        expected_columns = OFFICIAL_STAGING_COLUMN_COUNTS[table_id]
        if len(schema_columns) != expected_columns:
            raise G2BRunnerError(
                f"G1 column count mismatch for {table_id}: {len(schema_columns)}"
            )
        if diff_tables[table_id].get("status") != "MATCH":
            raise G2BRunnerError(f"G1 schema diff is not MATCH for {table_id}")
        row_count = int(data_tables[table_id].get("row_count", -1))
        if row_count != table_spec.expected_rows:
            raise G2BRunnerError(f"G1 row count mismatch for {table_id}: {row_count}")
        observed_rows += row_count
        observed_columns += len(schema_columns)
    if observed_rows != EXPECTED_TOTAL_ROWS:
        raise G2BRunnerError("G1 data profile row total is not official")
    if observed_columns != OFFICIAL_STAGING_COLUMN_TOTAL:
        raise G2BRunnerError("G1 schema profile column total is not official")
    return schema_profile, data_profile


def _rule_projection(rule: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "logical_table_id",
        "source_column",
        "occurrence",
        "qualified_name",
        "declared_type",
        "observed_types",
        "target_type",
        "transform_policy",
        "null_policy",
        "whitespace_policy",
        "parse_failure_policy",
        "unit_status",
        "code_status",
        "mapping_status",
    )
    return {field: rule.get(field) for field in fields}


def _validate_g2a(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    rules: Sequence[TypedRule],
) -> None:
    for filename, document in documents.items():
        if document.get("g2a_status") != "PASS":
            raise G2BRunnerError(f"G2-A status is not PASS: {filename}")

    typed = documents["g2a_typed_rules.json"]
    reported_rules = typed.get("rules")
    if not isinstance(reported_rules, list):
        raise G2BRunnerError("G2-A typed rules must be a list")
    if len(reported_rules) != OFFICIAL_STAGING_COLUMN_TOTAL:
        raise G2BRunnerError("G2-A typed rule count is not 207")
    expected_rules = [rule.to_dict() for rule in rules]
    if not all(isinstance(rule, Mapping) for rule in reported_rules):
        raise G2BRunnerError("G2-A typed rule entries must be objects")
    if [_rule_projection(rule) for rule in reported_rules] != expected_rules:
        raise G2BRunnerError("G2-A typed rules differ from current G1 profiles")
    typed_summary = typed.get("summary")
    if not isinstance(typed_summary, Mapping):
        raise G2BRunnerError("G2-A typed summary is missing")
    if int(typed_summary.get("parse_error_count", -1)) != 0:
        raise G2BRunnerError("G2-A contains parse errors")

    coverage = documents["g2a_coverage_matrix.json"]
    validation = coverage.get("validation")
    if not isinstance(validation, Mapping) or validation.get("is_valid") is not True:
        raise G2BRunnerError("G2-A coverage validation is not PASS")
    if int(validation.get("actual_source_column_count", -1)) != OFFICIAL_STAGING_COLUMN_TOTAL:
        raise G2BRunnerError("G2-A coverage does not contain 207 source columns")

    lineage = documents["g2a_lineage_summary.json"]
    summary = lineage.get("summary")
    if not isinstance(summary, Mapping):
        raise G2BRunnerError("G2-A lineage summary is missing")
    if lineage.get("sources_immutable") is not True:
        raise G2BRunnerError("G2-A source immutability is not PASS")
    if lineage.get("g1_reports_immutable") is not True:
        raise G2BRunnerError("G2-A G1-report immutability is not PASS")
    if int(summary.get("source_row_count", -1)) != EXPECTED_TOTAL_ROWS:
        raise G2BRunnerError("G2-A lineage row count is not official")
    if int(summary.get("source_row_id_collision_count", -1)) != 0:
        raise G2BRunnerError("G2-A lineage contains source_row_id collisions")


def _validate_core_mapping_evidence(
    mappings: Sequence[CoreFieldMapping],
    *,
    schema_profile: Mapping[str, Any],
    rules: Sequence[TypedRule],
) -> None:
    schema_tables = _table_index(schema_profile, label="g1_schema_profile")
    schema_fields: dict[tuple[str, str], Mapping[str, Any]] = {}
    for table_id, table in schema_tables.items():
        columns = table.get("columns")
        if not isinstance(columns, list):
            raise G2BRunnerError(f"G1 schema columns missing for {table_id}")
        schema_fields.update(
            {
                (table_id, str(column.get("qualified_name"))): column
                for column in columns
                if isinstance(column, Mapping)
            }
        )
    typed_fields = {
        (rule.logical_table_id, str(rule.qualified_name)): rule for rule in rules
    }
    for mapping in mappings:
        identity = (mapping.logical_table_id, mapping.qualified_name)
        source = schema_fields.get(identity)
        rule = typed_fields.get(identity)
        if source is None or rule is None:
            raise G2BRunnerError(
                f"core mapping lacks official evidence: {identity[0]}.{identity[1]}"
            )
        if mapping.source_column != source.get("column_name"):
            raise G2BRunnerError(f"core mapping source mismatch: {mapping.semantic_field_key}")
        if mapping.official_schema_description != source.get("display_name"):
            raise G2BRunnerError(
                f"core mapping description differs from G1: {mapping.semantic_field_key}"
            )
        if mapping.target_type != rule.target_type.value:
            raise G2BRunnerError(
                f"core mapping target type differs from G2-A: {mapping.semantic_field_key}"
            )


def _rules_by_table(rules: Sequence[TypedRule]) -> dict[str, tuple[TypedRule, ...]]:
    grouped: dict[str, list[TypedRule]] = {table_id: [] for table_id in TABLE_SPECS}
    for rule in rules:
        if rule.logical_table_id not in grouped:
            raise G2BRunnerError(f"unexpected typed-rule table: {rule.logical_table_id}")
        grouped[rule.logical_table_id].append(rule)
    return {table_id: tuple(entries) for table_id, entries in grouped.items()}


def _run_offline_preflight(
    *,
    sources: tuple[SourceWorkbook, ...],
    schema: StagingSchemaSpec,
    rules: Sequence[TypedRule],
    data_profile: Mapping[str, Any],
) -> dict[str, Any]:
    source_by_table = {
        source.logical_table_id: source
        for source in sources
        if source.source_kind == "datarows"
    }
    if set(source_by_table) != set(TABLE_SPECS):
        raise G2BRunnerError("official datarows sources are incomplete")
    profile_by_table = _table_index(data_profile, label="g1_data_profile")
    rules_by_table = _rules_by_table(rules)
    global_row_ids: set[str] = set()
    status_counts: Counter[str] = Counter()
    tables: list[dict[str, Any]] = []

    for table in schema.tables:
        table_id = table.logical_table_id
        expected_rows = int(profile_by_table[table_id]["row_count"])
        observed_rows = 0
        table_row_ids: set[str] = set()
        table_status_counts: Counter[str] = Counter()
        for staged_row in iter_typed_rows(
            source=source_by_table[table_id],
            table=table,
            rules=rules_by_table[table_id],
            data_profile_table=profile_by_table[table_id],
        ):
            observed_rows += 1
            row_id = staged_row.lineage.source_row_id
            if row_id in table_row_ids or row_id in global_row_ids:
                raise G2BRunnerError(f"source_row_id collision during preflight: {table_id}")
            table_row_ids.add(row_id)
            global_row_ids.add(row_id)
            table_status_counts.update(staged_row.parse_statuses.values())
        if observed_rows != expected_rows or len(table_row_ids) != expected_rows:
            raise G2BRunnerError(f"offline preflight row validation failed for {table_id}")
        status_counts.update(table_status_counts)
        tables.append(
            {
                "logical_table_id": table_id,
                "expected_source_row_count": expected_rows,
                "observed_source_row_count": observed_rows,
                "unique_source_row_id_count": len(table_row_ids),
                "parse_status_counts": dict(sorted(table_status_counts.items())),
                "parse_error_count": table_status_counts.get("PARSE_ERROR", 0),
                "source_unchanged": True,
                "status": "PASS",
            }
        )

    source_rows = sum(table["observed_source_row_count"] for table in tables)
    preflight_pass = (
        source_rows == EXPECTED_TOTAL_ROWS
        and len(global_row_ids) == EXPECTED_TOTAL_ROWS
        and status_counts.get("PARSE_ERROR", 0) == 0
    )
    if not preflight_pass:
        raise G2BRunnerError("offline typed-row preflight did not match G2-A")
    return {
        "status": "PASS",
        "table_count": len(tables),
        "source_row_count": source_rows,
        "unique_source_row_id_count": len(global_row_ids),
        "source_row_id_collision_count": source_rows - len(global_row_ids),
        "parse_status_counts": dict(sorted(status_counts.items())),
        "parse_error_count": status_counts.get("PARSE_ERROR", 0),
        "source_rows_copied_to_report": False,
        "tables": tables,
    }


def _bound_probe_value(target_type: TargetType, *, malicious_text: bool = False) -> Any:
    if target_type is TargetType.TEXT:
        return (
            "__g2b_parameter_'_--_probe__"
            if malicious_text
            else "__g2b_parameter_probe__"
        )
    if target_type is TargetType.DECIMAL:
        return Decimal("0")
    if target_type is TargetType.INTEGER:
        return 0
    if target_type is TargetType.DATE:
        return date(2000, 1, 1)
    if target_type is TargetType.TIMESTAMP:
        return datetime(2000, 1, 1)
    raise G2BRunnerError(f"no query probe for target type: {target_type.value}")


def _compile_query_preflight(
    *,
    schema: StagingSchemaSpec,
) -> tuple[dict[str, Any], Any]:
    confirmed = tuple(get_confirmed_core_fields())
    registry = build_trusted_query_registry(schema, CORE_FIELD_MAPPINGS)
    compiler = StructuredQueryCompiler(registry)
    by_table: dict[str, list[CoreFieldMapping]] = {}
    for field in confirmed:
        by_table.setdefault(field.logical_table_id, []).append(field)

    def first_with(operation: str) -> CoreFieldMapping:
        try:
            return next(
                field
                for field in confirmed
                if operation in field.allowed_operations
            )
        except StopIteration as error:
            raise G2BRunnerError(f"no confirmed Priority A field supports {operation}") from error

    eq_field = first_with("EQ")
    range_field = first_with("GE")
    sort_field = first_with("SORT")
    multi_fields: list[CoreFieldMapping] | None = None
    for table_fields in by_table.values():
        eq_fields = [
            field for field in table_fields if "EQ" in field.allowed_operations
        ]
        if len(eq_fields) >= 2:
            multi_fields = eq_fields[:2]
            break
    if multi_fields is None:
        raise G2BRunnerError("no table has two confirmed EQ fields")

    query_shapes: list[tuple[str, StructuredQueryContract]] = [
        (
            "eq",
            StructuredQueryContract(
                product_scope=eq_field.logical_table_id,
                filters=(
                    StructuredFilter(
                        field=eq_field.semantic_field_key,
                        operator=FilterOperator.EQ,
                        value=_bound_probe_value(TargetType(eq_field.target_type)),
                    ),
                ),
                projections=(eq_field.semantic_field_key,),
            ),
        ),
        (
            "range",
            StructuredQueryContract(
                product_scope=range_field.logical_table_id,
                filters=(
                    StructuredFilter(
                        field=range_field.semantic_field_key,
                        operator=FilterOperator.GE,
                        value=_bound_probe_value(TargetType(range_field.target_type)),
                    ),
                ),
                projections=(range_field.semantic_field_key,),
            ),
        ),
        (
            "multi_filter",
            StructuredQueryContract(
                product_scope=multi_fields[0].logical_table_id,
                filters=tuple(
                    StructuredFilter(
                        field=field.semantic_field_key,
                        operator=FilterOperator.EQ,
                        value=_bound_probe_value(TargetType(field.target_type)),
                    )
                    for field in multi_fields
                ),
                projections=(multi_fields[0].semantic_field_key,),
            ),
        ),
        (
            "sort_asc",
            StructuredQueryContract(
                product_scope=sort_field.logical_table_id,
                projections=(sort_field.semantic_field_key,),
                sort=StructuredSort(
                    field=sort_field.semantic_field_key,
                    direction=SortDirection.ASC,
                ),
            ),
        ),
        (
            "sort_desc",
            StructuredQueryContract(
                product_scope=sort_field.logical_table_id,
                projections=(sort_field.semantic_field_key,),
                sort=StructuredSort(
                    field=sort_field.semantic_field_key,
                    direction=SortDirection.DESC,
                ),
            ),
        ),
        (
            "top_n",
            StructuredQueryContract(
                product_scope=sort_field.logical_table_id,
                projections=(sort_field.semantic_field_key,),
                sort=StructuredSort(
                    field=sort_field.semantic_field_key,
                    direction=SortDirection.DESC,
                ),
                limit=1,
            ),
        ),
        (
            "count",
            StructuredQueryContract(
                product_scope=eq_field.logical_table_id,
                filters=(
                    StructuredFilter(
                        field=eq_field.semantic_field_key,
                        operator=FilterOperator.EQ,
                        value=_bound_probe_value(TargetType(eq_field.target_type)),
                    ),
                ),
                aggregate=AggregateFunction.COUNT,
            ),
        ),
    ]

    results: dict[str, Any] = {}
    for name, query in query_shapes:
        compiled = compiler.compile(query)
        if compiled.sql.count("%s") != len(compiled.parameters):
            raise G2BRunnerError(f"query placeholder mismatch for {name}")
        if any(isinstance(value, str) and value in compiled.sql for value in compiled.parameters):
            raise G2BRunnerError(f"bound query value was interpolated for {name}")
        results[name] = {
            "status": "PASS",
            "product_scope": query.product_scope,
            "filter_count": len(query.filters),
            "projection_count": len(query.projections),
            "parameter_count": len(compiled.parameters),
            "values_bound": True,
        }

    injection_field = next(
        field
        for field in confirmed
        if field.target_type == TargetType.TEXT.value and "EQ" in field.allowed_operations
    )
    injection_probe = str(
        _bound_probe_value(TargetType.TEXT, malicious_text=True)
    )
    injection_query = StructuredQueryContract(
        product_scope=injection_field.logical_table_id,
        filters=(
            StructuredFilter(
                field=injection_field.semantic_field_key,
                operator=FilterOperator.EQ,
                value=injection_probe,
            ),
        ),
        projections=(injection_field.semantic_field_key,),
    )
    injection_compiled = compiler.compile(injection_query)
    injection_safe = (
        injection_probe not in injection_compiled.sql
        and injection_probe in injection_compiled.parameters
    )
    if not injection_safe:
        raise G2BRunnerError("structured query injection probe was not safely bound")
    return (
        {
            "status": "PASS",
            "trusted_table_count": registry.table_count,
            "trusted_field_count": registry.field_count,
            "compiled_shapes": results,
            "identifier_policy": "TRUSTED_REGISTRY_ONLY",
            "value_policy": "BOUND_PARAMETERS_ONLY",
            "injection_binding_probe": "PASS",
            "query_values_copied_to_report": False,
            "free_form_sql_accepted": False,
            "nl2sql_enabled": False,
        },
        registry,
    )


def _database_not_run(reason: str, *, requested: bool) -> dict[str, Any]:
    return {
        "status": "NOT_RUN",
        "execution_requested": requested,
        "reason": reason,
        "credentials_reported": False,
        "connection_string_reported": False,
        "load": None,
        "live_query_validation": {
            "status": "NOT_RUN",
            "reason": "No live PostgreSQL query execution was performed.",
        },
    }


def _run_database_load(
    *,
    execute_database: bool,
    connection: ConnectionLike | None,
    database_url: str | None,
    sources: tuple[SourceWorkbook, ...],
    schema: StagingSchemaSpec,
    rules: Sequence[TypedRule],
    data_profile: Mapping[str, Any],
    batch_size: int,
) -> dict[str, Any]:
    if not execute_database:
        if connection is not None or database_url:
            raise G2BRunnerError(
                "database configuration requires execute_database=True"
            )
        return _database_not_run(
            "PostgreSQL execution was not requested; offline contracts only.",
            requested=False,
        )
    if connection is not None and database_url:
        raise G2BRunnerError("supply either an injected connection or DATABASE_URL, not both")
    if connection is None and not database_url:
        return _database_not_run(
            "PostgreSQL execution was requested, but DATABASE_URL is not configured.",
            requested=True,
        )

    owned_connection = False
    if connection is None:
        try:
            import psycopg
        except ImportError:
            return {
                "status": "BLOCKED",
                "execution_requested": True,
                "reason": "The PostgreSQL driver is unavailable in this environment.",
                "error_type": "ImportError",
                "credentials_reported": False,
                "connection_string_reported": False,
                "load": None,
                "live_query_validation": {
                    "status": "NOT_RUN",
                    "reason": "The PostgreSQL driver was unavailable.",
                },
            }
        try:
            connection = psycopg.connect(database_url, connect_timeout=5)
            owned_connection = True
        except Exception as error:
            return {
                "status": "BLOCKED",
                "execution_requested": True,
                "reason": (
                    "PostgreSQL connection could not be established with the "
                    "supplied environment configuration."
                ),
                "error_type": type(error).__name__,
                "credentials_reported": False,
                "connection_string_reported": False,
                "load": None,
                "live_query_validation": {
                    "status": "NOT_RUN",
                    "reason": "A PostgreSQL connection was not established.",
                },
            }

    try:
        stats = load_all(
            connection,
            sources=sources,
            schema=schema,
            rules=rules,
            data_profile=data_profile,
            batch_size=batch_size,
            replace=True,
            create_tables=True,
        )
        if not stats.validated:
            raise G2BRunnerError("PostgreSQL loader returned an unvalidated result")
        return {
            "status": "PASS",
            "execution_requested": True,
            "reason": (
                "All four typed staging tables were loaded and validated in one "
                "transaction."
            ),
            "credentials_reported": False,
            "connection_string_reported": False,
            "load": stats.to_dict(),
            # Loading and query execution are separate gates.  G2-B cannot be
            # marked PASS until all required query shapes run against the
            # loaded PostgreSQL data and their result shapes are validated.
            "live_query_validation": {
                "status": "NOT_RUN",
                "reason": "Live Core QA query-shape validation is not implemented yet.",
            },
        }
    except Exception as error:
        return {
            "status": "FAIL",
            "execution_requested": True,
            "reason": (
                "PostgreSQL staging load or validation failed; transaction rollback "
                "was requested."
            ),
            "error_type": type(error).__name__,
            "credentials_reported": False,
            "connection_string_reported": False,
            "load": None,
            "live_query_validation": {
                "status": "NOT_RUN",
                "reason": "The staging load did not complete.",
            },
        }
    finally:
        if owned_connection and connection is not None:
            connection.close()  # type: ignore[attr-defined]


def run_g2b(
    raw_dir: str | Path,
    schema_dir: str | Path,
    g1_report_dir: str | Path,
    g2a_report_dir: str | Path,
    output_dir: str | Path,
    *,
    execute_database: bool = False,
    connection: ConnectionLike | None = None,
    database_url: str | None = None,
    batch_size: int = 1_000,
) -> dict[str, Any]:
    """Validate G1/G2-A, scan all typed rows, and optionally load PostgreSQL."""

    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise G2BRunnerError("batch_size must be a positive integer")
    raw_directory = _resolve_directory(raw_dir, label="raw_dir")
    schema_directory = _resolve_directory(schema_dir, label="schema_dir")
    g1_directory = _resolve_directory(g1_report_dir, label="g1_report_dir")
    g2a_directory = _resolve_directory(g2a_report_dir, label="g2a_report_dir")
    output = _validate_output_directory(
        output_dir,
        protected_directories=(
            raw_directory,
            schema_directory,
            g1_directory,
            g2a_directory,
        ),
    )

    sources = discover_workbooks(raw_directory, schema_directory)
    g1_documents, g1_paths = _load_report_set(
        g1_directory,
        filenames=REPORT_FILENAMES,
        label="G1 report directory",
    )
    g2a_documents, g2a_paths = _load_report_set(
        g2a_directory,
        filenames=G2A_REPORT_FILENAMES,
        label="G2-A report directory",
    )
    input_report_fingerprints = _fingerprint_files((*g1_paths, *g2a_paths))
    schema_profile, data_profile = _validate_g1(g1_documents, sources)
    rules = tuple(build_rules_from_profiles(schema_profile, data_profile))
    _validate_g2a(g2a_documents, rules=rules)
    _validate_core_mapping_evidence(
        CORE_FIELD_MAPPINGS,
        schema_profile=schema_profile,
        rules=rules,
    )
    schema = build_staging_schema(rules)
    core_mapping_registry = build_core_field_registry()
    if core_mapping_registry["validation"]["is_valid"] is not True:
        raise G2BRunnerError("Priority A core mapping registry is invalid")
    structured_query_preflight, trusted_registry = _compile_query_preflight(
        schema=schema
    )
    offline_preflight = _run_offline_preflight(
        sources=sources,
        schema=schema,
        rules=rules,
        data_profile=data_profile,
    )

    if not verify_sources_unchanged(sources):
        raise G2BRunnerError("a source workbook changed during offline preflight")
    if not _fingerprints_unchanged(input_report_fingerprints):
        raise G2BRunnerError("a G1 or G2-A report changed during offline preflight")

    database = _run_database_load(
        execute_database=execute_database,
        connection=connection,
        database_url=database_url,
        sources=sources,
        schema=schema,
        rules=rules,
        data_profile=data_profile,
        batch_size=batch_size,
    )
    sources_unchanged = verify_sources_unchanged(sources)
    input_reports_unchanged = _fingerprints_unchanged(input_report_fingerprints)
    if not sources_unchanged or not input_reports_unchanged:
        raise G2BRunnerError(
            "a source workbook or upstream report changed during G2-B"
        )

    database_status = database["status"]
    live_query_status = database["live_query_validation"]["status"]
    g2b_status = (
        "PASS"
        if database_status == "PASS" and live_query_status == "PASS"
        else "FAIL"
        if database_status == "FAIL" or live_query_status == "FAIL"
        else "PARTIAL"
    )
    generated_at = _utc_now()
    core_field_mapping = {
        "g2b_format_version": G2B_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "mapping_status": "PASS",
        **core_mapping_registry,
    }
    structured_schema = {
        "g2b_format_version": G2B_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "schema_status": "PASS",
        "storage": schema.to_dict(),
        "trusted_query_registry": {
            "table_count": trusted_registry.table_count,
            "agent_allowed_field_count": trusted_registry.field_count,
            "field_selection": "CONFIRMED_PRIORITY_A_ONLY",
            "trusted_identifiers_only": True,
            "bound_values_only": True,
        },
        "policies": {
            "technical_primary_key": "source_row_id",
            "business_primary_key_inferred": False,
            "automatic_trim_applied": False,
            "zero_imputation_applied": False,
            "unit_or_scale_conversion_applied": False,
            "free_form_sql_enabled": False,
            "nl2sql_enabled": False,
        },
    }
    validation_summary = {
        "g2b_format_version": G2B_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "g2b_status": g2b_status,
        "upstream_validation": {
            "g1_status": "PASS",
            "g2a_status": "PASS",
            "g1_and_g2a_reports_unchanged": input_reports_unchanged,
        },
        "source_integrity": {
            "source_file_count": len(sources),
            "checked_attributes": ["size_bytes", "modified_time_ns", "sha256"],
            "size_mtime_sha256_unchanged": sources_unchanged,
            "source_rows_copied_to_reports": False,
            "source_files_modified": False,
        },
        "offline_preflight": offline_preflight,
        "structured_query_preflight": structured_query_preflight,
        "database": database,
        "scope_guardrails": {
            "vector_retrieval_implemented": False,
            "graph_retrieval_implemented": False,
            "ontology_ttl_implemented": False,
            "hcx_implemented": False,
            "tax_or_cost_logic_implemented": False,
            "external_api_implemented": False,
        },
    }
    report_paths = write_g2b_reports(
        output,
        core_field_mapping=core_field_mapping,
        structured_schema=structured_schema,
        validation_summary=validation_summary,
    )
    if tuple(Path(path).name for path in report_paths.values()) != G2B_REPORT_FILENAMES:
        raise AssertionError("G2-B writer did not produce the exact report contract")
    return {
        "status": g2b_status,
        "offline_preflight_status": offline_preflight["status"],
        "database_status": database_status,
        "source_row_count": offline_preflight["source_row_count"],
        "source_row_id_collision_count": offline_preflight[
            "source_row_id_collision_count"
        ],
        "staging_table_count": len(schema.tables),
        "staging_source_column_count": schema.source_column_count,
        "agent_allowed_field_count": trusted_registry.field_count,
        "sources_unchanged": sources_unchanged,
        "upstream_reports_unchanged": input_reports_unchanged,
        "report_paths": report_paths,
    }


__all__ = [
    "G2B_FORMAT_VERSION",
    "G2BRunnerError",
    "run_g2b",
]
