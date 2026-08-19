"""Atomic writers for the five aggregate-only G2-A artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .constants import G2A_REPORT_FILENAMES


class G2AReportError(ValueError):
    """Raised when an output directory would violate the report contract."""


def _json_text(document: Mapping[str, Any]) -> str:
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
    typed_rules: Mapping[str, Any],
    coverage_matrix: Mapping[str, Any],
    lineage_summary: Mapping[str, Any],
    mapping_review: Mapping[str, Any],
) -> str:
    """Build a bounded review summary without source rows or arbitrary samples."""

    typed_summary = typed_rules["summary"]
    coverage_summary = coverage_matrix["summary"]
    concept_counts = mapping_review["summary"]["concept_status_counts"]
    lines = [
        "# G2-A Typed Staging Specification and Coverage Summary",
        "",
        f"- G2-A status: **{typed_rules['g2a_status']}**",
        f"- Source rows verified: {lineage_summary['summary']['source_row_count']:,}",
        f"- Typed rules: {typed_summary['rule_count']}",
        f"- Coverage: {coverage_summary['covered_column_count']}/{coverage_summary['actual_column_count']} ({coverage_summary['coverage_ratio']:.0%})",
        f"- Parse errors: {typed_summary['parse_error_count']:,}",
        f"- Source immutable check: {'PASS' if lineage_summary['sources_immutable'] else 'FAIL'}",
        "- Scope: deterministic Raw → Typed Staging → Coverage contract only; no database or query engine was created.",
        "",
        "## Target type distribution",
        "",
        "| Target type | Columns |",
        "|---|---:|",
    ]
    for target, count in typed_summary["target_type_counts"].items():
        lines.append(f"| {target} | {count} |")

    lines.extend(
        [
            "",
            "## Mapping review",
            "",
            f"- CONFIRMED: {concept_counts.get('CONFIRMED', 0)}",
            f"- CANDIDATE: {concept_counts.get('CANDIDATE', 0)}",
            f"- UNMAPPED: {concept_counts.get('UNMAPPED', 0)}",
            "- Official schema display names are review labels only. No canonical cross-table concept was confirmed.",
            "",
            "## Parse and null policy",
            "",
        ]
    )
    for status, count in typed_summary["parse_status_counts"].items():
        lines.append(f"- {status}: {count:,}")

    conflict_columns = typed_summary.get("trim_conflict_columns", [])
    uniqueness_changes = typed_summary.get(
        "identifier_uniqueness_change_columns", []
    )
    lines.extend(
        [
            "",
            "## Whitespace review",
            "",
            f"- Columns with hypothetical trim collisions: {len(conflict_columns)}",
            f"- Conflict columns: {', '.join(conflict_columns) or 'none'}",
            f"- Identifier columns whose uniqueness changes: {', '.join(uniqueness_changes) or 'none'}",
            "- Automatic trim applied: false",
            "",
            "## Source row lineage",
            "",
            f"- Algorithm: {lineage_summary['source_row_id_contract']['algorithm']}",
            f"- Version: {lineage_summary['source_row_id_contract']['version']}",
            "- Inputs: logical table, source file SHA-256, source sheet, source Excel row.",
            "- source_row_id is technical lineage and is never treated as a business primary key.",
            "",
            "## G2-B review blockers",
            "",
        ]
    )
    blockers = mapping_review.get("g2b_blockers", [])
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Raw values are preserved by the row-local ParseResult contract but are not copied into these aggregate reports.",
            "- Missing, empty, whitespace-only, parse-error, and unsupported results remain distinguishable.",
            "- Numeric-looking text is not converted unless its official schema type is numeric.",
            "- Units, currencies, percentages, code meanings, and cross-table financial concepts are not inferred.",
            "- No PostgreSQL, SQL engine, NL2SQL, Vector, Graph, Ontology TTL, HCX, tax, or external data integration is included.",
            "",
        ]
    )
    return "\n".join(lines)


def write_g2a_reports(
    output_dir: Path,
    *,
    typed_rules: dict[str, Any],
    coverage_matrix: dict[str, Any],
    lineage_summary: dict[str, Any],
    mapping_review: dict[str, Any],
) -> dict[str, str]:
    """Create or atomically replace exactly the five declared G2-A reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(
        path.name
        for path in output_dir.iterdir()
        if path.name not in G2A_REPORT_FILENAMES
    )
    if unexpected:
        raise G2AReportError(
            "output_dir contains unexpected entries; refusing to delete or overwrite: "
            + ", ".join(unexpected)
        )

    documents = {
        "g2a_typed_rules.json": _json_text(typed_rules),
        "g2a_coverage_matrix.json": _json_text(coverage_matrix),
        "g2a_lineage_summary.json": _json_text(lineage_summary),
        "g2a_mapping_review.json": _json_text(mapping_review),
        "g2a_summary.md": build_summary_markdown(
            typed_rules=typed_rules,
            coverage_matrix=coverage_matrix,
            lineage_summary=lineage_summary,
            mapping_review=mapping_review,
        ),
    }
    if tuple(documents) != G2A_REPORT_FILENAMES:
        raise AssertionError("internal report order does not match G2-A contract")
    for filename, content in documents.items():
        _atomic_write_text(output_dir / filename, content)
    return {
        filename: str((output_dir / filename).resolve()) for filename in documents
    }


__all__ = [
    "G2AReportError",
    "build_summary_markdown",
    "write_g2a_reports",
]
