"""End-to-end orchestration for the read-only G1 profiling run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .comparison import compare_schema_and_data
from .constants import EXPECTED_TOTAL_ROWS, PROFILE_FORMAT_VERSION, TABLE_SPECS
from .discovery import (
    DiscoveryError,
    SourceWorkbook,
    discover_workbooks,
    sha256_file,
)
from .reports import write_reports
from .workbook_metadata import WorkbookMetadata, inspect_workbook_metadata
from .workbook_profile import extract_schema_profile, profile_data_workbook


def _is_within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def _validate_output_directory(
    output_dir: str | Path,
    sources: tuple[SourceWorkbook, ...],
) -> Path:
    output = Path(output_dir).expanduser().resolve()
    source_directories = {source.path.parent.resolve() for source in sources}
    if any(_is_within(output, source_directory) for source_directory in source_directories):
        raise DiscoveryError(
            "output_dir must not be inside either read-only source directory"
        )
    return output


def _source_is_unchanged(source: SourceWorkbook) -> bool:
    stat = source.path.stat()
    return (
        stat.st_size == source.size_bytes
        and stat.st_mtime_ns == source.modified_time_ns
        and sha256_file(source.path) == source.sha256
    )


def _manifest_entry(
    source: SourceWorkbook,
    *,
    metadata: WorkbookMetadata,
    schema_by_id: dict[str, dict[str, Any]],
    data_by_id: dict[str, dict[str, Any]],
    source_immutable: bool,
) -> dict[str, Any]:
    if source.source_kind == "datarows":
        expected_rows: int | None = TABLE_SPECS[source.logical_table_id].expected_rows
        observed_rows: int | None = data_by_id[source.logical_table_id]["row_count"]
        match_status = "MATCH" if expected_rows == observed_rows else "MISMATCH"
        selected_sheet = data_by_id[source.logical_table_id]["selected_data_sheet"]
        header_row: int | None = data_by_id[source.logical_table_id]["header_row"]
        column_count: int | None = data_by_id[source.logical_table_id]["column_count"]
    else:
        expected_rows = None
        observed_rows = None
        match_status = "NOT_APPLICABLE"
        selected_sheet = schema_by_id[source.logical_table_id]["selected_schema_sheet"]
        header_row = schema_by_id[source.logical_table_id]["header_row"]
        column_count = schema_by_id[source.logical_table_id]["schema_definition_count"]
    return {
        "source_kind": source.source_kind,
        "physical_filename": source.physical_filename,
        "logical_table_id": source.logical_table_id,
        "extension": source.extension,
        "size_bytes": source.size_bytes,
        "sha256": source.sha256,
        "modified_at_utc": source.modified_at_utc,
        "sheet_names": metadata.sheet_names,
        "sheets": [sheet.to_dict() for sheet in metadata.sheets],
        "selected_sheet": selected_sheet,
        "header_row": header_row,
        "column_count": column_count,
        "expected_rows": expected_rows,
        "observed_rows": observed_rows,
        "match_status": match_status,
        "source_immutable": source_immutable,
    }


def run_profiling(
    raw_dir: str | Path,
    schema_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Discover, profile, verify immutability, and write the five G1 reports."""

    sources = discover_workbooks(raw_dir, schema_dir)
    output = _validate_output_directory(output_dir, sources)
    metadata_by_path = {
        source.path: inspect_workbook_metadata(source.path) for source in sources
    }
    schema_sources = {
        source.logical_table_id: source
        for source in sources
        if source.source_kind == "schema"
    }
    data_sources = {
        source.logical_table_id: source
        for source in sources
        if source.source_kind == "datarows"
    }

    schema_tables = [
        extract_schema_profile(
            schema_sources[table_id], metadata_by_path[schema_sources[table_id].path]
        )
        for table_id in TABLE_SPECS
    ]
    schema_by_id = {table["logical_table_id"]: table for table in schema_tables}
    data_tables = [
        profile_data_workbook(
            data_sources[table_id],
            schema_by_id[table_id],
            metadata_by_path[data_sources[table_id].path],
        )
        for table_id in TABLE_SPECS
    ]
    data_by_id = {table["logical_table_id"]: table for table in data_tables}
    diff_tables = [
        compare_schema_and_data(schema_by_id[table_id], data_by_id[table_id])
        for table_id in TABLE_SPECS
    ]

    immutable_by_path = {source.path: _source_is_unchanged(source) for source in sources}
    sources_immutable = all(immutable_by_path.values())
    if not sources_immutable:
        changed = [
            source.physical_filename
            for source in sources
            if not immutable_by_path[source.path]
        ]
        raise RuntimeError(
            "source workbook changed during profiling; no reports were written: "
            + ", ".join(changed)
        )

    observed_total_rows = sum(table["row_count"] for table in data_tables)
    row_counts_match = all(
        data_by_id[table_id]["row_count"] == TABLE_SPECS[table_id].expected_rows
        for table_id in TABLE_SPECS
    )
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest_files = [
        _manifest_entry(
            source,
            metadata=metadata_by_path[source.path],
            schema_by_id=schema_by_id,
            data_by_id=data_by_id,
            source_immutable=immutable_by_path[source.path],
        )
        for source in sorted(
            sources,
            key=lambda item: (item.logical_table_id, item.source_kind),
        )
    ]
    g1_data_status = (
        "PASS"
        if len(sources) == 8
        and len(data_tables) == 4
        and len(schema_tables) == 4
        and row_counts_match
        and observed_total_rows == EXPECTED_TOTAL_ROWS
        and sources_immutable
        else "FAIL"
    )
    manifest = {
        "profile_format_version": PROFILE_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "expected_total_rows": EXPECTED_TOTAL_ROWS,
        "observed_total_rows": observed_total_rows,
        "total_row_match_status": (
            "MATCH" if observed_total_rows == EXPECTED_TOTAL_ROWS else "MISMATCH"
        ),
        "sources_immutable": sources_immutable,
        "g1_data_status": g1_data_status,
        "files": manifest_files,
    }
    schema_document = {
        "profile_format_version": PROFILE_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "tables": schema_tables,
    }
    data_document = {
        "profile_format_version": PROFILE_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "distinct_count_method": "typed_sha256_digest_in_ephemeral_sqlite",
        "source_rows_copied": False,
        "arbitrary_value_samples_copied": False,
        "bounded_aggregate_evidence_included": True,
        "tables": data_tables,
    }
    diff_document = {
        "profile_format_version": PROFILE_FORMAT_VERSION,
        "generated_at_utc": generated_at,
        "comparison_semantics": "exact column name plus duplicate occurrence",
        "tables": diff_tables,
    }
    report_paths = write_reports(
        output,
        manifest=manifest,
        schema_profile=schema_document,
        data_profile=data_document,
        schema_diff=diff_document,
    )
    return {
        "status": g1_data_status,
        "file_count": len(sources),
        "logical_table_count": len(data_tables),
        "expected_total_rows": EXPECTED_TOTAL_ROWS,
        "observed_total_rows": observed_total_rows,
        "sources_unchanged": sources_immutable,
        "report_paths": report_paths,
    }
