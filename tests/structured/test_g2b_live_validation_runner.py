"""Tests for wiring read-only Live Structured Query Validation into the
existing G2-B report set via ``run_g2b_live_validation``.

These tests never touch a real PostgreSQL instance: ``run_live_query_validation``
is monkeypatched with controlled results, exactly like the opt-in real-database
integration test (``tests/integration/test_g2b_live_query_validation.py``)
covers the genuine production path separately. What is tested here is the
runner/report wiring itself: that a PASS/FAIL live-validation result is
recorded correctly, that the DB loader is never invoked by this path, that no
credential or query value ever reaches the written report, and that every
other previously-recorded report section survives untouched.
"""

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
from pipeline.structured.reports import G2B_REPORT_FILENAMES
from pipeline.structured.schema import (
    OFFICIAL_STAGING_COLUMN_COUNTS,
    OFFICIAL_STAGING_COLUMN_TOTAL,
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


def _seven_shapes_pass() -> dict[str, Any]:
    shape_names = (
        "eq",
        "range",
        "multi_filter",
        "sort_asc",
        "sort_desc",
        "top_n",
        "count",
    )
    return {
        "status": "PASS",
        "product_scope": "PREF01N001",
        "row_limit_used": 5,
        "top_n_limit_used": 3,
        "shapes": {
            name: {"name": name, "status": "PASS", "reason": "ok", "checks": {"ok": True}}
            for name in shape_names
        },
        "parse_status_gate": {"name": "parse_status_gate", "status": "PASS", "reason": "ok", "checks": {}},
        "query_values_copied_to_report": False,
        "reason": "All seven required shapes matched an independent read-only oracle.",
    }


def _one_shape_fails() -> dict[str, Any]:
    result = _seven_shapes_pass()
    result["status"] = "FAIL"
    result["shapes"]["count"] = {
        "name": "count",
        "status": "FAIL",
        "reason": "COUNT value did not match the independent oracle",
        "checks": {"aggregate_value_matches_independent_oracle": False},
    }
    result["reason"] = "One or more required shapes failed; see 'shapes' for the specific reason."
    return result


def _prepare_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path, Path]:
    raw_dir = tmp_path / "raw"
    schema_dir = tmp_path / "schema"
    g1_dir = tmp_path / "g1"
    g2a_dir = tmp_path / "g2a"
    g2b_dir = tmp_path / "g2b"
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

    # First produce a real, internally-consistent baseline report (database
    # execution not requested), so structured_schema/core_field_mapping
    # exactly match what a genuine run_g2b would have written.
    baseline = runner.run_g2b(raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir)
    assert baseline["status"] == "PARTIAL"

    # Now simulate "the operator already ran a real PostgreSQL load
    # separately" by rewriting only the database section to PASS, exactly as
    # a genuine execute_database=True run would have recorded it (never via
    # run_g2b_live_validation itself, which must not be able to fabricate
    # this).
    validation_path = g2b_dir / "g2b_validation_summary.json"
    validation_summary = json.loads(validation_path.read_text(encoding="utf-8"))
    validation_summary["database"] = {
        "status": "PASS",
        "execution_requested": True,
        "reason": "All four typed staging tables were loaded and validated in one transaction.",
        "credentials_reported": False,
        "connection_string_reported": False,
        "load": {"rows_loaded": EXPECTED_TOTAL_ROWS, "tables_loaded": 4},
        "live_query_validation": {
            "status": "NOT_RUN",
            "reason": "Live Core QA query-shape validation is not implemented yet.",
        },
    }
    validation_summary["g2b_status"] = "PARTIAL"
    structured_schema_path = g2b_dir / "g2b_structured_schema.json"
    structured_schema = json.loads(structured_schema_path.read_text(encoding="utf-8"))
    core_field_mapping_path = g2b_dir / "g2b_core_field_mapping.json"
    core_field_mapping = json.loads(core_field_mapping_path.read_text(encoding="utf-8"))
    from pipeline.structured.reports import write_g2b_reports

    write_g2b_reports(
        g2b_dir,
        core_field_mapping=core_field_mapping,
        structured_schema=structured_schema,
        validation_summary=validation_summary,
    )
    return raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir


def test_all_seven_shapes_pass_yields_live_query_validation_pass_and_g2b_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir = _prepare_environment(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        runner, "run_live_query_validation", lambda *_a, **_k: _seven_shapes_pass()
    )

    result = runner.run_g2b_live_validation(
        raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir, database_url="postgresql://fake/db"
    )

    assert result["status"] == "PASS"
    assert result["database_status"] == "PASS"
    assert result["live_query_validation_status"] == "PASS"

    validation_summary = json.loads(
        (g2b_dir / "g2b_validation_summary.json").read_text(encoding="utf-8")
    )
    assert validation_summary["g2b_status"] == "PASS"
    assert validation_summary["database"]["status"] == "PASS"
    assert validation_summary["database"]["live_query_validation"]["status"] == "PASS"
    assert set(validation_summary["database"]["live_query_validation"]["shapes"]) == {
        "eq",
        "range",
        "multi_filter",
        "sort_asc",
        "sort_desc",
        "top_n",
        "count",
    }


def test_one_live_query_shape_fail_keeps_g2b_status_off_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir = _prepare_environment(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        runner, "run_live_query_validation", lambda *_a, **_k: _one_shape_fails()
    )

    result = runner.run_g2b_live_validation(
        raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir, database_url="postgresql://fake/db"
    )

    assert result["status"] != "PASS"
    assert result["status"] == "FAIL"
    validation_summary = json.loads(
        (g2b_dir / "g2b_validation_summary.json").read_text(encoding="utf-8")
    )
    assert validation_summary["g2b_status"] != "PASS"
    assert validation_summary["database"]["live_query_validation"]["shapes"]["count"]["status"] == "FAIL"


def test_no_credential_or_query_value_is_written_to_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir = _prepare_environment(
        tmp_path, monkeypatch
    )
    secret_url = "postgresql://realuser:realpassword@db.internal:5432/mirae"
    monkeypatch.setattr(
        runner, "run_live_query_validation", lambda *_a, **_k: _seven_shapes_pass()
    )

    runner.run_g2b_live_validation(
        raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir, database_url=secret_url
    )

    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in g2b_dir.iterdir()
    )
    assert secret_url not in combined
    assert "realpassword" not in combined
    assert "realuser" not in combined
    assert "DATABASE_URL" not in combined


def test_live_validation_path_never_invokes_the_database_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir = _prepare_environment(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        runner, "run_live_query_validation", lambda *_a, **_k: _seven_shapes_pass()
    )

    def _forbidden(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the PostgreSQL loader must never run during live validation")

    monkeypatch.setattr(runner, "load_all", _forbidden)
    monkeypatch.setattr(runner, "iter_typed_rows", _forbidden)

    result = runner.run_g2b_live_validation(
        raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir, database_url="postgresql://fake/db"
    )

    assert result["status"] == "PASS"


def test_existing_report_sections_survive_a_live_validation_only_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir = _prepare_environment(
        tmp_path, monkeypatch
    )
    before = json.loads(
        (g2b_dir / "g2b_validation_summary.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        runner, "run_live_query_validation", lambda *_a, **_k: _seven_shapes_pass()
    )

    runner.run_g2b_live_validation(
        raw_dir, schema_dir, g1_dir, g2a_dir, g2b_dir, database_url="postgresql://fake/db"
    )

    after = json.loads(
        (g2b_dir / "g2b_validation_summary.json").read_text(encoding="utf-8")
    )
    assert after["database"]["load"] == before["database"]["load"]
    assert after["offline_preflight"] == before["offline_preflight"]
    assert after["source_integrity"] == before["source_integrity"]
    assert after["upstream_validation"] == before["upstream_validation"]
    assert after["structured_query_preflight"] == before["structured_query_preflight"]
