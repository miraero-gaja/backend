from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from mappings.core import CORE_FIELD_MAPPINGS
from pipeline.normalize.constants import G2A_REPORT_FILENAMES
from pipeline.normalize.scanner import build_rules_from_profiles
from pipeline.profiling.constants import EXPECTED_TOTAL_ROWS, REPORT_FILENAMES, TABLE_SPECS
from pipeline.profiling.discovery import SourceWorkbook, sha256_file
from pipeline.structured import runner
from pipeline.structured.reports import (
    G2B_REPORT_FILENAMES,
    G2BReportError,
    write_g2b_reports,
)
from pipeline.structured.schema import (
    OFFICIAL_STAGING_COLUMN_COUNTS,
    OFFICIAL_STAGING_COLUMN_TOTAL,
    build_staging_schema,
)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _declared_type(target_type: str) -> str:
    return {
        "TEXT": "text",
        "DECIMAL": "numeric",
        "INTEGER": "bigint",
        "DATE": "date",
        "TIMESTAMP": "timestamp without time zone",
    }[target_type]


def _synthetic_profiles() -> tuple[dict[str, Any], dict[str, Any]]:
    mappings_by_table: dict[str, list[Any]] = {table_id: [] for table_id in TABLE_SPECS}
    for mapping in CORE_FIELD_MAPPINGS:
        mappings_by_table[mapping.logical_table_id].append(mapping)

    schema_tables: list[dict[str, Any]] = []
    data_tables: list[dict[str, Any]] = []
    for table_id, count in OFFICIAL_STAGING_COLUMN_COUNTS.items():
        reviewed = mappings_by_table[table_id]
        definitions: list[tuple[str, str, str | None]] = [
            (
                mapping.source_column,
                _declared_type(mapping.target_type),
                mapping.official_schema_description,
            )
            for mapping in reviewed
        ]
        filler_index = 1
        while len(definitions) < count:
            name = f"synthetic_field_{filler_index:03d}"
            filler_index += 1
            if any(existing[0] == name for existing in definitions):
                continue
            definitions.append((name, "text", None))

        schema_columns: list[dict[str, Any]] = []
        data_columns: list[dict[str, Any]] = []
        for position, (name, declared_type, display_name) in enumerate(
            definitions, start=1
        ):
            qualified = f"{name}#1"
            schema_columns.append(
                {
                    "position": position,
                    "column_name": name,
                    "occurrence": 1,
                    "qualified_name": qualified,
                    "declared_type": declared_type,
                    "display_name": display_name,
                    "declared_unit": None,
                }
            )
            data_columns.append(
                {
                    "position": position,
                    "column_name": name,
                    "occurrence": 1,
                    "qualified_name": qualified,
                    "observed_types": [
                        "number"
                        if declared_type in {"numeric", "bigint"}
                        else "string"
                    ],
                    "enum_code_candidate": False,
                    "boolean_code_candidate": False,
                }
            )
        schema_tables.append(
            {"logical_table_id": table_id, "columns": schema_columns}
        )
        data_tables.append(
            {
                "logical_table_id": table_id,
                "selected_data_sheet": "datarows",
                "header_row": 1,
                "last_data_row": TABLE_SPECS[table_id].expected_rows + 1,
                "row_count": TABLE_SPECS[table_id].expected_rows,
                "columns": data_columns,
            }
        )
    return {"tables": schema_tables}, {"tables": data_tables}


def _synthetic_sources(
    raw_dir: Path,
    schema_dir: Path,
) -> tuple[SourceWorkbook, ...]:
    sources: list[SourceWorkbook] = []
    for source_kind, directory in (("datarows", raw_dir), ("schema", schema_dir)):
        for table_id in TABLE_SPECS:
            path = directory / f"{table_id}_{source_kind}.xlsx"
            path.write_bytes(f"{table_id}:{source_kind}".encode("ascii"))
            stat = path.stat()
            sources.append(
                SourceWorkbook(
                    source_kind=source_kind,  # type: ignore[arg-type]
                    logical_table_id=table_id,
                    path=path,
                    physical_filename=path.name,
                    extension=".xlsx",
                    size_bytes=stat.st_size,
                    modified_time_ns=stat.st_mtime_ns,
                    modified_at_utc=datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).isoformat().replace("+00:00", "Z"),
                    sha256=sha256_file(path),
                )
            )
    return tuple(sources)


def _write_upstream_reports(
    *,
    g1_dir: Path,
    g2a_dir: Path,
    sources: tuple[SourceWorkbook, ...],
    schema_profile: dict[str, Any],
    data_profile: dict[str, Any],
) -> None:
    g1_dir.mkdir()
    g2a_dir.mkdir()
    manifest = {
        "observed_total_rows": EXPECTED_TOTAL_ROWS,
        "sources_immutable": True,
        "g1_data_status": "PASS",
        "files": [
            {
                "logical_table_id": source.logical_table_id,
                "source_kind": source.source_kind,
                "physical_filename": source.physical_filename,
                "extension": source.extension,
                "size_bytes": source.size_bytes,
                "modified_at_utc": source.modified_at_utc,
                "sha256": source.sha256,
                "source_immutable": True,
            }
            for source in sources
        ],
    }
    schema_diff = {
        "tables": [
            {"logical_table_id": table_id, "status": "MATCH"}
            for table_id in TABLE_SPECS
        ]
    }
    g1_documents = {
        "g1_file_manifest.json": manifest,
        "g1_schema_profile.json": schema_profile,
        "g1_data_profile.json": data_profile,
        "g1_schema_diff.json": schema_diff,
    }
    for filename, document in g1_documents.items():
        _write_json(g1_dir / filename, document)
    (g1_dir / "g1_summary.md").write_text("# synthetic G1\n", encoding="utf-8")
    assert sorted(path.name for path in g1_dir.iterdir()) == sorted(REPORT_FILENAMES)

    typed_rules = build_rules_from_profiles(schema_profile, data_profile)
    g2a_documents = {
        "g2a_typed_rules.json": {
            "g2a_status": "PASS",
            "rules": [rule.to_dict() for rule in typed_rules],
            "summary": {"parse_error_count": 0},
        },
        "g2a_coverage_matrix.json": {
            "g2a_status": "PASS",
            "validation": {
                "is_valid": True,
                "actual_source_column_count": OFFICIAL_STAGING_COLUMN_TOTAL,
            },
        },
        "g2a_lineage_summary.json": {
            "g2a_status": "PASS",
            "sources_immutable": True,
            "g1_reports_immutable": True,
            "summary": {
                "source_row_count": EXPECTED_TOTAL_ROWS,
                "source_row_id_collision_count": 0,
            },
        },
        "g2a_mapping_review.json": {"g2a_status": "PASS"},
    }
    for filename, document in g2a_documents.items():
        _write_json(g2a_dir / filename, document)
    (g2a_dir / "g2a_summary.md").write_text("# synthetic G2-A\n", encoding="utf-8")
    assert sorted(path.name for path in g2a_dir.iterdir()) == sorted(
        G2A_REPORT_FILENAMES
    )


def _offline_pass() -> dict[str, Any]:
    return {
        "status": "PASS",
        "table_count": 4,
        "source_row_count": EXPECTED_TOTAL_ROWS,
        "unique_source_row_id_count": EXPECTED_TOTAL_ROWS,
        "source_row_id_collision_count": 0,
        "parse_status_counts": {"OK": 1},
        "parse_error_count": 0,
        "source_rows_copied_to_report": False,
        "tables": [
            {
                "logical_table_id": table_id,
                "expected_source_row_count": spec.expected_rows,
                "observed_source_row_count": spec.expected_rows,
                "unique_source_row_id_count": spec.expected_rows,
                "parse_status_counts": {"OK": 1},
                "parse_error_count": 0,
                "source_unchanged": True,
                "status": "PASS",
            }
            for table_id, spec in TABLE_SPECS.items()
        ],
    }


def test_query_preflight_compiles_all_required_shapes_with_bound_values() -> None:
    schema_profile, data_profile = _synthetic_profiles()
    schema = build_staging_schema(
        build_rules_from_profiles(schema_profile, data_profile)
    )

    result, registry = runner._compile_query_preflight(schema=schema)

    assert result["status"] == "PASS"
    assert set(result["compiled_shapes"]) == {
        "eq",
        "range",
        "multi_filter",
        "sort_asc",
        "sort_desc",
        "top_n",
        "count",
    }
    assert all(
        shape["values_bound"] for shape in result["compiled_shapes"].values()
    )
    assert result["injection_binding_probe"] == "PASS"
    assert result["query_values_copied_to_report"] is False
    assert registry.table_count == 4
    assert registry.field_count == 49


def test_runner_writes_exact_partial_reports_when_database_url_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_dir = tmp_path / "raw"
    schema_dir = tmp_path / "schema"
    g1_dir = tmp_path / "g1"
    g2a_dir = tmp_path / "g2a"
    output_dir = tmp_path / "g2b"
    raw_dir.mkdir()
    schema_dir.mkdir()
    sources = _synthetic_sources(raw_dir, schema_dir)
    schema_profile, data_profile = _synthetic_profiles()
    _write_upstream_reports(
        g1_dir=g1_dir,
        g2a_dir=g2a_dir,
        sources=sources,
        schema_profile=schema_profile,
        data_profile=data_profile,
    )
    monkeypatch.setattr(runner, "discover_workbooks", lambda *_: sources)
    monkeypatch.setattr(runner, "_run_offline_preflight", lambda **_: _offline_pass())

    result = runner.run_g2b(
        raw_dir,
        schema_dir,
        g1_dir,
        g2a_dir,
        output_dir,
        execute_database=True,
    )

    assert result["status"] == "PARTIAL"
    assert result["database_status"] == "NOT_RUN"
    assert result["staging_table_count"] == 4
    assert result["staging_source_column_count"] == OFFICIAL_STAGING_COLUMN_TOTAL
    assert result["agent_allowed_field_count"] == 49
    assert sorted(path.name for path in output_dir.iterdir()) == sorted(
        G2B_REPORT_FILENAMES
    )
    validation = json.loads(
        (output_dir / "g2b_validation_summary.json").read_text(encoding="utf-8")
    )
    assert validation["database"]["status"] == "NOT_RUN"
    assert validation["database"]["live_query_validation"]["status"] == "NOT_RUN"
    assert "DATABASE_URL is not configured" in validation["database"]["reason"]
    assert validation["source_integrity"]["source_files_modified"] is False
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.iterdir()
    )
    assert "__g2b_parameter_probe__" not in combined
    assert "raw_value" not in combined
    assert "normalized_value" not in combined


def test_report_writer_refuses_unexpected_entries_and_row_or_secret_keys(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    output.mkdir()
    (output / "keep.txt").write_text("user file", encoding="utf-8")
    with pytest.raises(G2BReportError, match="unexpected entries"):
        write_g2b_reports(
            output,
            core_field_mapping={},
            structured_schema={},
            validation_summary={},
        )

    clean = tmp_path / "clean"
    with pytest.raises(G2BReportError, match="source row payload"):
        write_g2b_reports(
            clean,
            core_field_mapping={"raw_value": "not allowed"},
            structured_schema={},
            validation_summary={},
        )
    with pytest.raises(G2BReportError, match="secret-shaped"):
        write_g2b_reports(
            clean,
            core_field_mapping={"database_password": "not allowed"},
            structured_schema={},
            validation_summary={},
        )


def test_cli_has_no_database_url_argument_and_reads_env_only_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pipeline.structured import cli

    observed: list[dict[str, Any]] = []

    def fake_run_g2b(*args: Any, **kwargs: Any) -> dict[str, Any]:
        observed.append(kwargs)
        return {"status": "PARTIAL"}

    monkeypatch.setattr(cli, "run_g2b", fake_run_g2b)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example.invalid/db")
    required = [
        "--raw-dir",
        "raw",
        "--schema-dir",
        "schema",
        "--g1-report-dir",
        "g1",
        "--g2a-report-dir",
        "g2a",
        "--output-dir",
        "g2b",
    ]

    assert cli.main(required) == 2
    assert observed[-1]["execute_database"] is False
    assert observed[-1]["database_url"] is None
    assert cli.main([*required, "--execute-db"]) == 2
    assert observed[-1]["execute_database"] is True
    assert observed[-1]["database_url"].startswith("postgresql://")
    assert "password" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*required, "--database-url", "forbidden"])
