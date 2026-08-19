"""Atomic, aggregate-only report writers for the G2-B structured baseline."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


G2B_REPORT_FILENAMES = (
    "g2b_core_field_mapping.json",
    "g2b_structured_schema.json",
    "g2b_validation_summary.json",
    "g2b_summary.md",
)


class G2BReportError(ValueError):
    """Raised when a report would violate the bounded G2-B contract."""


_FORBIDDEN_EXACT_KEYS = {
    "raw_record",
    "raw_value",
    "normalized_value",
    "typed_values",
}
_FORBIDDEN_SECRET_KEY_PARTS = (
    "api_key",
    "database_url",
    "password",
    "secret",
)


def _validate_aggregate_only(value: Any, *, path: str = "$") -> None:
    """Fail closed if a document contains row payloads or secret-shaped keys."""

    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key)
            lowered = key.casefold()
            if lowered in _FORBIDDEN_EXACT_KEYS:
                raise G2BReportError(f"source row payload key is forbidden at {path}.{key}")
            if any(part in lowered for part in _FORBIDDEN_SECRET_KEY_PARTS):
                raise G2BReportError(f"secret-shaped key is forbidden at {path}.{key}")
            _validate_aggregate_only(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _validate_aggregate_only(nested, path=f"{path}[{index}]")


def _json_text(document: Mapping[str, Any]) -> str:
    _validate_aggregate_only(document)
    return json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
        allow_nan=False,
    ) + "\n"


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


def build_summary_markdown(
    *,
    core_field_mapping: Mapping[str, Any],
    structured_schema: Mapping[str, Any],
    validation_summary: Mapping[str, Any],
) -> str:
    """Build a bounded human review without copying source or query values."""

    mapping = core_field_mapping["summary"]
    storage = structured_schema["storage"]
    preflight = validation_summary["offline_preflight"]
    database = validation_summary["database"]
    queries = validation_summary["structured_query_preflight"]
    lines = [
        "# G2-B Structured Baseline Summary",
        "",
        f"- G2-B status: **{validation_summary['g2b_status']}**",
        f"- Offline typed-row preflight: **{preflight['status']}**",
        f"- PostgreSQL load: **{database['status']}**",
        f"- Live PostgreSQL query validation: **{database['live_query_validation']['status']}**",
        f"- Structured query compile checks: **{queries['status']}**",
        f"- Staging shape: {storage['table_count']} tables / {storage['source_column_count']} source columns",
        f"- Source rows verified offline: {preflight['source_row_count']:,}",
        f"- Agent-allowed fields: {mapping['agent_allowed_field_count']}",
        "",
        "## Priority A semantic review",
        "",
        f"- CONFIRMED: {mapping['semantic_status_counts']['CONFIRMED']}",
        f"- NEED_REVIEW: {mapping['semantic_status_counts']['NEED_REVIEW']}",
        f"- UNMAPPED: {mapping['semantic_status_counts']['UNMAPPED']}",
        "- Only CONFIRMED fields are available to the Structured Tool.",
        "- Semantic keys remain table-scoped; no cross-product concept merge is claimed.",
        "",
        "## PostgreSQL staging",
        "",
        "- `source_row_id` is the technical primary key; no business primary key is inferred.",
        "- All official source columns are materialized as nullable typed columns.",
        "- Exact raw-value envelopes, parse states, and source lineage are retained in staging.",
        "- Automatic trim, zero imputation, unit conversion, and scale conversion are disabled.",
        f"- Database result: {database['reason']}",
        "",
        "## Deterministic query boundary",
        "",
        "- Supported shapes: EQ, range comparison, multi-filter, ASC/DESC sort, Top-N/limit, and COUNT.",
        "- Identifiers come only from the trusted registry; all user values and limits are bound parameters.",
        "- Free-form SQL and NL2SQL are outside this baseline.",
        "",
        "## Evidence and remaining scope",
        "",
        "- Row queries select `source_row_id`, logical table ID, exact raw envelopes, and normalized values for evidence construction.",
        "- Aggregate COUNT currently returns a deterministic count without fabricated row-level evidence.",
        "- Full ontology, aliases, unit/currency semantics, vector/graph retrieval, HCX, tax, cost logic, and external APIs remain out of scope.",
        "",
    ]
    return "\n".join(lines)


def write_g2b_reports(
    output_dir: Path,
    *,
    core_field_mapping: dict[str, Any],
    structured_schema: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, str]:
    """Create or atomically replace exactly the four declared G2-B reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(
        path.name
        for path in output_dir.iterdir()
        if path.name not in G2B_REPORT_FILENAMES
    )
    if unexpected:
        raise G2BReportError(
            "output_dir contains unexpected entries; refusing to delete or overwrite: "
            + ", ".join(unexpected)
        )

    documents = {
        "g2b_core_field_mapping.json": _json_text(core_field_mapping),
        "g2b_structured_schema.json": _json_text(structured_schema),
        "g2b_validation_summary.json": _json_text(validation_summary),
        "g2b_summary.md": build_summary_markdown(
            core_field_mapping=core_field_mapping,
            structured_schema=structured_schema,
            validation_summary=validation_summary,
        ),
    }
    if tuple(documents) != G2B_REPORT_FILENAMES:
        raise AssertionError("internal report order does not match G2-B contract")
    for filename, content in documents.items():
        _atomic_write_text(output_dir / filename, content)

    observed = tuple(sorted(path.name for path in output_dir.iterdir()))
    if observed != tuple(sorted(G2B_REPORT_FILENAMES)):
        raise G2BReportError("G2-B report directory does not match the exact contract")
    return {
        filename: str((output_dir / filename).resolve()) for filename in documents
    }


__all__ = [
    "G2B_REPORT_FILENAMES",
    "G2BReportError",
    "build_summary_markdown",
    "write_g2b_reports",
]
