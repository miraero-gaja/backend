"""Atomic writers for the exact five non-row-copying G1 reports."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .constants import REPORT_FILENAMES


def _atomic_write_text(path: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary_path = Path(stream.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _json_text(document: dict[str, Any]) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
        allow_nan=False,
    ) + "\n"


def _join_names(entries: list[dict[str, Any]], *, key: str = "column_name") -> str:
    return ", ".join(str(entry[key]) for entry in entries) if entries else "없음"


def build_summary_markdown(
    *,
    manifest: dict[str, Any],
    schema_profile: dict[str, Any],
    data_profile: dict[str, Any],
    schema_diff: dict[str, Any],
) -> str:
    """Build a bounded human review; never include source row/example values."""

    lines = [
        "# G1 Data Profiling Summary",
        "",
        f"- Data profiling status: **{manifest['g1_data_status']}**",
        f"- Expected total rows: {manifest['expected_total_rows']:,}",
        f"- Observed total rows: {manifest['observed_total_rows']:,}",
        f"- Source immutable check: {'PASS' if manifest['sources_immutable'] else 'FAIL'}",
        "- Scope: schema/data truth only; canonical schema, finance meaning, units, and keys are not inferred.",
        "",
        "## File inventory",
        "",
        "| Kind | Logical table | Physical filename | SHA-256 | Sheets |",
        "|---|---|---|---|---|",
    ]
    for file_entry in manifest["files"]:
        sheet_names = ", ".join(file_entry["sheet_names"])
        lines.append(
            f"| {file_entry['source_kind']} | {file_entry['logical_table_id']} | "
            f"{file_entry['physical_filename']} | `{file_entry['sha256']}` | "
            f"{sheet_names} |"
        )

    lines.extend(
        [
            "",
            "## Row and column verification",
            "",
            "| Logical table | Expected rows | Observed rows | Row status | Schema columns | Data columns | Column status |",
            "|---|---:|---:|---|---:|---:|---|",
        ]
    )
    schema_by_id = {
        table["logical_table_id"]: table for table in schema_profile["tables"]
    }
    data_by_id = {table["logical_table_id"]: table for table in data_profile["tables"]}
    diff_by_id = {table["logical_table_id"]: table for table in schema_diff["tables"]}
    raw_entries = [
        entry for entry in manifest["files"] if entry["source_kind"] == "datarows"
    ]
    for entry in raw_entries:
        table_id = entry["logical_table_id"]
        lines.append(
            f"| {table_id} | {entry['expected_rows']:,} | {entry['observed_rows']:,} | "
            f"{entry['match_status']} | {schema_by_id[table_id]['schema_definition_count']} | "
            f"{data_by_id[table_id]['column_count']} | {diff_by_id[table_id]['status']} |"
        )

    lines.extend(["", "## Schema differences", ""])
    for table in schema_diff["tables"]:
        lines.extend(
            [
                f"### {table['logical_table_id']}",
                "",
                f"- Schema only: {_join_names(table['missing_in_data'])}",
                f"- Data only: {_join_names(table['missing_in_schema'])}",
                f"- Exact order match: {table['exact_column_order_match']}",
                "",
            ]
        )

    lines.extend(["## Identifier evidence", ""])
    for table in data_profile["tables"]:
        declared_key = table["declared_key_analysis"]
        candidates = ", ".join(
            candidate["qualified_name"] for candidate in table["candidate_identifiers"]
        ) or "없음"
        lines.extend(
            [
                f"### {table['logical_table_id']}",
                "",
                f"- Schema-declared key status: {declared_key['status']}",
                f"- Schema-declared columns: {', '.join(declared_key.get('columns', [])) or '없음'}",
                f"- Statistical candidates: {candidates}",
                "- Candidate means observed unique and nonblank only; it is not a confirmed primary key.",
                "",
            ]
        )

    lines.extend(["## Major quality evidence", ""])
    for table in data_profile["tables"]:
        null_columns = sorted(
            (column for column in table["columns"] if column["null_count"]),
            key=lambda column: (-column["null_ratio"], column["position"]),
        )
        whitespace_columns = [
            column
            for column in table["columns"]
            if column["leading_or_trailing_whitespace_count"]
        ]
        mixed_columns = [
            column for column in table["columns"] if column["mixed_value_types"]
        ]
        error_count = sum(column["excel_error_count"] for column in table["columns"])
        explicit_units = sum(
            column["declared_unit"] is not None for column in table["columns"]
        )
        lines.extend(
            [
                f"### {table['logical_table_id']}",
                "",
                f"- Columns with observed null/blank: {len(null_columns)}",
                f"- Highest null/blank columns (max 10): {', '.join(column['qualified_name'] for column in null_columns[:10]) or '없음'}",
                f"- Columns with leading/trailing whitespace: {len(whitespace_columns)}",
                f"- Columns with mixed observed types: {len(mixed_columns)}",
                f"- Excel error cells: {error_count}",
                f"- Explicit schema unit declarations: {explicit_units}",
                "",
            ]
        )

    lines.extend(
        [
            "## Interpretation guardrails",
            "",
            "- Numeric-like, date-like, code-like, enum, and identifier results are evidence-based candidates only.",
            "- An eight-digit valid calendar value is a lexical/value-shape date candidate, not a confirmed date datatype.",
            "- A numeric magnitude is never reinterpreted as a percentage, currency, or unit.",
            "- Distinct counts use typed SHA-256 digests in an ephemeral SQLite store; source rows and arbitrary value samples are not written to reports.",
            "- Requested bounded evidence such as numeric/date extrema and boolean-code representations is included when observed.",
            "- Schema example values are intentionally omitted from generated reports.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    output_dir: Path,
    *,
    manifest: dict[str, Any],
    schema_profile: dict[str, Any],
    data_profile: dict[str, Any],
    schema_diff: dict[str, Any],
) -> dict[str, str]:
    """Atomically create only the five required G1 report files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    documents = {
        "g1_file_manifest.json": _json_text(manifest),
        "g1_schema_profile.json": _json_text(schema_profile),
        "g1_data_profile.json": _json_text(data_profile),
        "g1_schema_diff.json": _json_text(schema_diff),
        "g1_summary.md": build_summary_markdown(
            manifest=manifest,
            schema_profile=schema_profile,
            data_profile=data_profile,
            schema_diff=schema_diff,
        ),
    }
    if tuple(documents) != REPORT_FILENAMES:
        raise AssertionError("internal report contract does not match REPORT_FILENAMES")
    for filename, content in documents.items():
        _atomic_write_text(output_dir / filename, content)
    return {filename: str((output_dir / filename).resolve()) for filename in documents}
