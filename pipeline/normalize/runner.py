"""End-to-end orchestration for the read-only G2-A contract build."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mappings.concepts import build_concept_registry
from mappings.coverage import build_coverage_registry
from pipeline.profiling.constants import EXPECTED_TOTAL_ROWS, TABLE_SPECS
from pipeline.profiling.discovery import (
    SourceWorkbook,
    discover_workbooks,
    sha256_file,
    verify_sources_unchanged,
)
from pipeline.profiling.workbook_metadata import inspect_workbook_metadata
from pipeline.profiling.workbook_profile import extract_schema_profile

from .constants import (
    EXPECTED_COVERAGE_COLUMN_COUNT,
    G2A_FORMAT_VERSION,
    G2A_REPORT_FILENAMES,
)
from .lineage import SOURCE_ROW_ID_VERSION
from .reports import write_g2a_reports
from .scanner import build_rules_from_profiles, scan_workbooks


G1_REPORT_FILENAMES = (
    "g1_file_manifest.json",
    "g1_schema_profile.json",
    "g1_data_profile.json",
    "g1_schema_diff.json",
    "g1_summary.md",
)


class G2ARunnerError(ValueError):
    """Raised when G1 evidence or the official source snapshot is inconsistent."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def _resolve_directory(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise G2ARunnerError(f"{label} is not a directory: {resolved}")
    return resolved


def _validate_output_directory(
    output_dir: str | Path,
    *,
    sources: tuple[SourceWorkbook, ...],
    g1_report_dir: Path,
) -> Path:
    output = Path(output_dir).expanduser().resolve()
    protected_directories = {
        g1_report_dir,
        *(source.path.parent.resolve() for source in sources),
    }
    if any(_is_within(output, protected) for protected in protected_directories):
        raise G2ARunnerError(
            "output_dir must not be inside a source or G1-report directory"
        )
    if any(_is_within(protected, output) for protected in protected_directories):
        raise G2ARunnerError(
            "output_dir must not contain a source or G1-report directory"
        )
    return output


def _fingerprint_files(paths: list[Path]) -> dict[Path, tuple[int, int, str]]:
    return {
        path: (path.stat().st_size, path.stat().st_mtime_ns, sha256_file(path))
        for path in paths
    }


def _fingerprints_unchanged(
    fingerprints: Mapping[Path, tuple[int, int, str]],
) -> bool:
    for path, expected in fingerprints.items():
        stat = path.stat()
        observed = (stat.st_size, stat.st_mtime_ns, sha256_file(path))
        if observed != expected:
            return False
    return True


def _load_g1_documents(
    g1_report_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[Path]]:
    entries = sorted(path.name for path in g1_report_dir.iterdir())
    if entries != sorted(G1_REPORT_FILENAMES):
        missing = sorted(set(G1_REPORT_FILENAMES) - set(entries))
        unexpected = sorted(set(entries) - set(G1_REPORT_FILENAMES))
        raise G2ARunnerError(
            "G1 report directory must contain exactly the five G1 artifacts; "
            f"missing={missing}, unexpected={unexpected}"
        )

    paths = [g1_report_dir / filename for filename in G1_REPORT_FILENAMES]
    if not all(path.is_file() for path in paths):
        raise G2ARunnerError("every G1 artifact must be a regular file")

    documents: list[dict[str, Any]] = []
    for filename in G1_REPORT_FILENAMES[:4]:
        try:
            payload = json.loads((g1_report_dir / filename).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise G2ARunnerError(f"cannot read valid UTF-8 JSON: {filename}") from error
        if not isinstance(payload, dict):
            raise G2ARunnerError(f"G1 report must be a JSON object: {filename}")
        documents.append(payload)
    manifest, schema_profile, data_profile, schema_diff = documents
    return manifest, schema_profile, data_profile, schema_diff, paths


def _validate_g1_manifest(
    manifest: Mapping[str, Any],
    sources: tuple[SourceWorkbook, ...],
) -> None:
    if manifest.get("g1_data_status") != "PASS":
        raise G2ARunnerError("G1 manifest status is not PASS")
    if manifest.get("sources_immutable") is not True:
        raise G2ARunnerError("G1 manifest does not confirm source immutability")
    if int(manifest.get("observed_total_rows", -1)) != EXPECTED_TOTAL_ROWS:
        raise G2ARunnerError("G1 manifest total row count is not the official total")

    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list):
        raise G2ARunnerError("G1 manifest files must be a list")
    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in manifest_files:
        if not isinstance(entry, Mapping):
            raise G2ARunnerError("G1 manifest file entry must be an object")
        identity = (str(entry.get("logical_table_id")), str(entry.get("source_kind")))
        if identity in indexed:
            raise G2ARunnerError(f"duplicate G1 manifest source identity: {identity}")
        indexed[identity] = entry

    expected_identities = {
        (source.logical_table_id, source.source_kind) for source in sources
    }
    if set(indexed) != expected_identities:
        raise G2ARunnerError("G1 manifest source identities do not match discovery")
    for source in sources:
        entry = indexed[(source.logical_table_id, source.source_kind)]
        expected = {
            "physical_filename": source.physical_filename,
            "size_bytes": source.size_bytes,
            "sha256": source.sha256,
            "source_immutable": True,
        }
        for field, value in expected.items():
            if entry.get(field) != value:
                raise G2ARunnerError(
                    f"G1 manifest mismatch for {source.logical_table_id}/"
                    f"{source.source_kind}: {field}"
                )


def _table_index(document: Mapping[str, Any], *, label: str) -> dict[str, Mapping[str, Any]]:
    tables = document.get("tables")
    if not isinstance(tables, list):
        raise G2ARunnerError(f"{label}.tables must be a list")
    indexed: dict[str, Mapping[str, Any]] = {}
    for table in tables:
        if not isinstance(table, Mapping):
            raise G2ARunnerError(f"{label} table must be an object")
        table_id = str(table.get("logical_table_id", ""))
        if table_id not in TABLE_SPECS or table_id in indexed:
            raise G2ARunnerError(f"invalid or duplicate {label} table: {table_id!r}")
        indexed[table_id] = table
    if list(indexed) != list(TABLE_SPECS):
        raise G2ARunnerError(f"{label} table order or identities do not match G1")
    return indexed


def _column_projection(column: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "position",
        "column_name",
        "occurrence",
        "qualified_name",
        "key_declaration",
        "declared_primary_key",
        "declared_type",
        "display_name",
        "declared_nullable",
        "declared_unit",
    )
    return {field: column.get(field) for field in fields}


def _reextract_and_validate_schema(
    *,
    sources: tuple[SourceWorkbook, ...],
    g1_schema_profile: Mapping[str, Any],
) -> dict[str, Any]:
    expected_tables = _table_index(g1_schema_profile, label="g1_schema_profile")
    schema_sources = {
        source.logical_table_id: source
        for source in sources
        if source.source_kind == "schema"
    }
    actual_tables: list[dict[str, Any]] = []
    for table_id in TABLE_SPECS:
        source = schema_sources[table_id]
        actual = extract_schema_profile(source, inspect_workbook_metadata(source.path))
        expected = expected_tables[table_id]
        for field in (
            "physical_filename",
            "selected_schema_sheet",
            "header_row",
            "schema_definition_count",
            "declared_primary_key_columns",
            "declared_unit_column_count",
        ):
            if actual.get(field) != expected.get(field):
                raise G2ARunnerError(
                    f"actual schema differs from G1 for {table_id}: {field}"
                )
        actual_columns = actual.get("columns")
        expected_columns = expected.get("columns")
        if not isinstance(actual_columns, list) or not isinstance(expected_columns, list):
            raise G2ARunnerError(f"schema columns missing for {table_id}")
        if [_column_projection(column) for column in actual_columns] != [
            _column_projection(column) for column in expected_columns
        ]:
            raise G2ARunnerError(
                f"actual schema columns differ from G1 for {table_id}"
            )
        actual_tables.append(actual)
    return {
        "profile_format_version": g1_schema_profile.get("profile_format_version"),
        "tables": actual_tables,
    }


def _validate_g1_profiles(
    *,
    schema_profile: Mapping[str, Any],
    data_profile: Mapping[str, Any],
    schema_diff: Mapping[str, Any],
) -> None:
    schema_tables = _table_index(schema_profile, label="g1_schema_profile")
    data_tables = _table_index(data_profile, label="g1_data_profile")
    diff_tables = _table_index(schema_diff, label="g1_schema_diff")
    column_count = 0
    row_count = 0
    for table_id in TABLE_SPECS:
        schema_columns = schema_tables[table_id].get("columns")
        data_columns = data_tables[table_id].get("columns")
        if not isinstance(schema_columns, list) or not isinstance(data_columns, list):
            raise G2ARunnerError(f"G1 profile columns missing for {table_id}")
        schema_ids = [column.get("qualified_name") for column in schema_columns]
        data_ids = [column.get("qualified_name") for column in data_columns]
        if schema_ids != data_ids:
            raise G2ARunnerError(f"G1 schema/data column order differs for {table_id}")
        if diff_tables[table_id].get("status") != "MATCH":
            raise G2ARunnerError(f"G1 schema diff is not MATCH for {table_id}")
        column_count += len(data_columns)
        row_count += int(data_tables[table_id].get("row_count", -1))
    if column_count != EXPECTED_COVERAGE_COLUMN_COUNT:
        raise G2ARunnerError(
            f"G1 source column count must be {EXPECTED_COVERAGE_COLUMN_COUNT}"
        )
    if row_count != EXPECTED_TOTAL_ROWS:
        raise G2ARunnerError(f"G1 data rows must total {EXPECTED_TOTAL_ROWS}")


def _identity(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record["logical_table_id"]), str(record["qualified_name"])


def _summarise_rules(
    rules: list[Any],
    parse_aggregates: list[dict[str, Any]],
    whitespace_aggregates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parse_by_id = {_identity(record): record for record in parse_aggregates}
    whitespace_by_id = {_identity(record): record for record in whitespace_aggregates}
    rule_entries: list[dict[str, Any]] = []
    target_counts: Counter[str] = Counter()
    transform_counts: Counter[str] = Counter()
    parse_counts: Counter[str] = Counter()
    whitespace_counts: Counter[str] = Counter()
    trim_conflicts: list[str] = []
    uniqueness_changes: list[str] = []
    parse_error_columns: list[str] = []

    for rule in rules:
        identity = (rule.logical_table_id, str(rule.qualified_name))
        parse = parse_by_id[identity]
        whitespace = whitespace_by_id[identity]
        target_counts[rule.target_type.value] += 1
        transform_counts[rule.transform_policy.value] += 1
        parse_counts.update(parse["status_counts"])
        whitespace_counts[str(whitespace["trim_status"])] += 1
        label = f"{identity[0]}.{identity[1]}"
        if whitespace.get("trim_collision_detected") is True:
            trim_conflicts.append(label)
        if whitespace.get("identifier_uniqueness_changed") is True:
            uniqueness_changes.append(label)
        if int(parse["parse_error_count"]) > 0:
            parse_error_columns.append(label)
        rule_entries.append(
            {
                **rule.to_dict(),
                "typed_status": (
                    "READY"
                    if rule.target_type.value != "UNSUPPORTED"
                    and int(parse["parse_error_count"]) == 0
                    else (
                        "UNSUPPORTED"
                        if rule.target_type.value == "UNSUPPORTED"
                        else "PARSE_REVIEW_REQUIRED"
                    )
                ),
                "parse_aggregate": parse,
                "whitespace_aggregate": whitespace,
            }
        )

    summary = {
        "rule_count": len(rule_entries),
        "target_type_counts": dict(sorted(target_counts.items())),
        "transform_policy_counts": dict(sorted(transform_counts.items())),
        "parse_status_counts": {
            status: parse_counts.get(status, 0)
            for status in (
                "OK",
                "MISSING",
                "EMPTY",
                "WHITESPACE_ONLY",
                "PARSE_ERROR",
                "NOT_APPLICABLE",
            )
        },
        "parse_error_count": parse_counts.get("PARSE_ERROR", 0),
        "parse_error_column_count": len(parse_error_columns),
        "parse_error_columns": parse_error_columns,
        "whitespace_status_counts": dict(sorted(whitespace_counts.items())),
        "trim_conflict_count": len(trim_conflicts),
        "trim_conflict_columns": trim_conflicts,
        "identifier_uniqueness_change_count": len(uniqueness_changes),
        "identifier_uniqueness_change_columns": uniqueness_changes,
    }
    return rule_entries, summary


def _pref01_key_blank_review(
    parse_aggregates: list[dict[str, Any]],
    key_analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    identity = ("PREF01N001", "pd_exg_mkt_cd#1")
    parse = next((record for record in parse_aggregates if _identity(record) == identity), None)
    key = next(
        (record for record in key_analyses if record["logical_table_id"] == identity[0]),
        None,
    )
    if parse is None or key is None:
        raise G2ARunnerError("PREF01 declared-key evidence is missing")
    counts = parse["status_counts"]
    return {
        "logical_table_id": identity[0],
        "qualified_name": identity[1],
        "missing_count": int(counts.get("MISSING", 0)),
        "empty_count": int(counts.get("EMPTY", 0)),
        "whitespace_only_count": int(counts.get("WHITESPACE_ONLY", 0)),
        "declared_key_rows_with_any_blank": int(
            key.get("rows_with_any_blank_before_trim", 0)
        ),
        "business_primary_key_enforced": False,
        "review_status": "NOT_NULL_BUSINESS_KEY_BLOCKED",
    }


def _g2b_blockers(
    *,
    typed_summary: Mapping[str, Any],
    concept_registry: Mapping[str, Any],
    pref01_review: Mapping[str, Any],
) -> list[str]:
    concept_counts = concept_registry["summary"]["status_counts"]
    return [
        "Choose an explicit preserve/trim rule for the "
        f"{typed_summary['trim_conflict_count']} columns where hypothetical trim "
        "collapses distinct raw values.",
        "Decide business-key policy for PREF01 only after reviewing its declared "
        f"key component blank count ({pref01_review['declared_key_rows_with_any_blank']}); "
        "G2-A does not enforce it as a primary key.",
        "Approve a canonical concept vocabulary and manually review "
        f"{concept_counts.get('CANDIDATE', 0)} candidates and "
        f"{concept_counts.get('UNMAPPED', 0)} unmapped fields; G2-A confirms none.",
        "Provide official units/currencies/percentage semantics; G1 declares units "
        "for 0 columns, so unit-based aggregation remains disabled.",
    ]


def run_g2a(
    raw_dir: str | Path,
    schema_dir: str | Path,
    g1_report_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Validate G1, scan read-only sources, and write exactly five G2-A reports."""

    sources = discover_workbooks(raw_dir, schema_dir)
    g1_directory = _resolve_directory(g1_report_dir, label="g1_report_dir")
    output = _validate_output_directory(
        output_dir,
        sources=sources,
        g1_report_dir=g1_directory,
    )
    manifest, g1_schema, data_profile, schema_diff, g1_paths = _load_g1_documents(
        g1_directory
    )
    g1_fingerprints = _fingerprint_files(g1_paths)

    _validate_g1_manifest(manifest, sources)
    _validate_g1_profiles(
        schema_profile=g1_schema,
        data_profile=data_profile,
        schema_diff=schema_diff,
    )
    actual_schema = _reextract_and_validate_schema(
        sources=sources,
        g1_schema_profile=g1_schema,
    )

    rules = build_rules_from_profiles(actual_schema, data_profile)
    scan = scan_workbooks(sources=sources, data_profile=data_profile, rules=rules)
    sources_immutable = verify_sources_unchanged(sources)
    g1_reports_immutable = _fingerprints_unchanged(g1_fingerprints)
    if not sources_immutable or not g1_reports_immutable:
        raise RuntimeError(
            "a source workbook or G1 report changed during G2-A; no reports were written"
        )

    rule_entries, typed_summary = _summarise_rules(
        rules,
        scan["parse_aggregates"],
        scan["whitespace_aggregates"],
    )
    concept_registry = build_concept_registry(actual_schema)
    coverage_matrix = build_coverage_registry(
        actual_schema,
        data_profile,
        typed_rules=rule_entries,
        parse_aggregates=scan["parse_aggregates"],
        whitespace_aggregates=scan["whitespace_aggregates"],
        expected_column_count=EXPECTED_COVERAGE_COLUMN_COUNT,
    )
    pref01_review = _pref01_key_blank_review(
        scan["parse_aggregates"], scan["declared_key_trim_analyses"]
    )
    blockers = _g2b_blockers(
        typed_summary=typed_summary,
        concept_registry=concept_registry,
        pref01_review=pref01_review,
    )
    generated_at = _utc_now()

    row_id_count = sum(
        int(table["source_row_id_count"]) for table in scan["lineage_tables"]
    )
    row_id_collisions = sum(
        int(table["source_row_id_collision_count"])
        for table in scan["lineage_tables"]
    )
    coverage_valid = bool(coverage_matrix["validation"]["is_valid"])
    concept_valid = bool(concept_registry["validation"]["is_valid"])
    g2a_pass = all(
        (
            len(rule_entries) == EXPECTED_COVERAGE_COLUMN_COUNT,
            int(scan["observed_total_rows"]) == EXPECTED_TOTAL_ROWS,
            row_id_count == EXPECTED_TOTAL_ROWS,
            row_id_collisions == 0,
            coverage_valid,
            concept_valid,
            sources_immutable,
            g1_reports_immutable,
        )
    )
    g2a_status = "PASS" if g2a_pass else "FAIL"

    typed_rules = {
        "g2a_format_version": G2A_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "g2a_status": g2a_status,
        "contract": {
            "source_values_preserved": True,
            "source_rows_copied_to_report": False,
            "schema_declared_type_controls_conversion": True,
            "numeric_implementation": "decimal.Decimal",
            "text_shape_promotion": False,
            "automatic_trim_applied": False,
            "zero_imputation_applied": False,
            "semantic_or_unit_inference_applied": False,
        },
        "rules": rule_entries,
        "summary": typed_summary,
    }
    coverage_matrix = {
        "g2a_format_version": G2A_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "g2a_status": g2a_status,
        **coverage_matrix,
    }
    lineage_summary = {
        "g2a_format_version": G2A_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "g2a_status": g2a_status,
        "sources_immutable": sources_immutable,
        "g1_reports_immutable": g1_reports_immutable,
        "actual_schema_revalidated": True,
        "source_row_id_contract": {
            "version": SOURCE_ROW_ID_VERSION,
            "algorithm": (
                "SHA-256 over a domain/version prefix and unsigned 8-byte "
                "length-prefixed UTF-8 components"
            ),
            "ordered_inputs": [
                "logical_table_id",
                "source_file_sha256",
                "source_sheet",
                "source_excel_row",
            ],
            "output_format": f"srid:{SOURCE_ROW_ID_VERSION}:<64 lowercase hex>",
            "business_primary_key_dependency": False,
        },
        "tables": scan["lineage_tables"],
        "declared_key_trim_analyses": scan["declared_key_trim_analyses"],
        "pref01_declared_key_blank_review": pref01_review,
        "summary": {
            "source_file_count": len(sources),
            "source_row_count": int(scan["observed_total_rows"]),
            "source_row_id_count": row_id_count,
            "source_row_id_collision_count": row_id_collisions,
            "identifier_uniqueness_change_count": typed_summary[
                "identifier_uniqueness_change_count"
            ],
            "business_primary_keys_enforced": 0,
        },
    }
    mapping_review = {
        "g2a_format_version": G2A_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "g2a_status": g2a_status,
        "policy": {
            "canonical_vocabulary_present": False,
            "confirmed_cross_table_concepts": 0,
            "schema_display_names_are_candidates_only": True,
            "unit_inference_performed": False,
            "business_primary_key_enforced": False,
        },
        "concept_registry": concept_registry,
        "summary": {
            "concept_status_counts": concept_registry["summary"]["status_counts"],
            "unit_status_counts": coverage_matrix["summary"]["unit_status_counts"],
            "code_status_counts": coverage_matrix["summary"]["code_status_counts"],
            "supported_operation_counts": coverage_matrix["summary"][
                "supported_operation_counts"
            ],
        },
        "g2b_blockers": blockers,
    }
    report_paths = write_g2a_reports(
        output,
        typed_rules=typed_rules,
        coverage_matrix=coverage_matrix,
        lineage_summary=lineage_summary,
        mapping_review=mapping_review,
    )
    if tuple(Path(path).name for path in report_paths.values()) != G2A_REPORT_FILENAMES:
        raise AssertionError("G2-A writer did not produce the exact report contract")
    return {
        "status": g2a_status,
        "source_file_count": len(sources),
        "source_row_count": int(scan["observed_total_rows"]),
        "rule_count": len(rule_entries),
        "coverage_column_count": coverage_matrix["summary"]["covered_column_count"],
        "coverage_ratio": coverage_matrix["summary"]["coverage_ratio"],
        "parse_error_count": typed_summary["parse_error_count"],
        "trim_conflict_count": typed_summary["trim_conflict_count"],
        "identifier_uniqueness_change_count": typed_summary[
            "identifier_uniqueness_change_count"
        ],
        "sources_unchanged": sources_immutable,
        "g1_reports_unchanged": g1_reports_immutable,
        "report_paths": report_paths,
    }


__all__ = ["G1_REPORT_FILENAMES", "G2ARunnerError", "run_g2a"]
