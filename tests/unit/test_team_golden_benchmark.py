"""Deterministic regression checks for the team evaluation simulation."""

from collections import Counter
from datetime import date

import pytest

from eval.error_taxonomy import FailureType
from eval.runners.team_golden import (
    _oracle_query,
    load_dataset,
    run_benchmark,
    write_report,
)


def test_team_golden_dataset_is_balanced_and_not_official_ground_truth() -> None:
    document, cases = load_dataset()

    assert document["dataset_kind"] == "evaluation_simulation"
    assert document["official_ground_truth"] is False
    assert document["source_snapshot"] == "2026-07-11"
    assert len(cases) == 40
    assert Counter(case.product_family for case in cases) == {
        "국내채권": 10,
        "국내 ETF": 10,
        "해외 ETF": 10,
        "공모펀드": 10,
    }
    assert all(
        case.case_id
        and case.question
        and case.expected_status
        and case.query_type
        and case.rationale
        and case.evidence_basis
        for case in cases
    )


def test_required_query_types_and_failure_taxonomy_are_covered() -> None:
    _, cases = load_dataset()
    query_types = {case.query_type for case in cases}
    assert {
        "EQ",
        "RANGE",
        "TOP_N",
        "FILTER_SORT_TOP_N",
        "COUNT",
        "NO_MATCH",
        "UNKNOWN_FIELD",
        "UNSUPPORTED_UNIT",
        "UNSUPPORTED_OPERATION",
        "AMBIGUOUS_FIELD",
        "AMBIGUOUS_SCOPE",
    } <= query_types
    assert {item.value for item in FailureType} == {
        "PARSE_ERROR",
        "PRODUCT_SCOPE_ERROR",
        "SEMANTIC_GROUNDING_ERROR",
        "OPERATION_ERROR",
        "UNSUPPORTED_FALSE_POSITIVE",
        "UNSUPPORTED_FALSE_NEGATIVE",
        "NO_MATCH_ERROR",
        "RESULT_MISMATCH",
        "ORDERING_ERROR",
        "EVIDENCE_ERROR",
        "GENERATION_VALIDATION_FALLBACK",
        "TOOL_FAILURE",
    }


def test_simulation_baseline_is_repeatable_and_fail_closed() -> None:
    report = run_benchmark(mode="simulation", use_hcx=False)

    assert report["official_ground_truth"] is False
    assert report["benchmark_mode"] == "simulation"
    assert report["live_data_used"] is False
    assert report["generation_mode"] == "deterministic"
    assert report["case_count"] == 40
    assert report["overall"] == {"passed": 40, "evaluated": 40, "rate": 1.0}
    assert report["metrics"]["result_set_correctness"] == {
        "passed": 19,
        "evaluated": 19,
        "rate": 1.0,
    }
    assert report["metrics"]["answer_schema_validity"]["rate"] == 1.0
    assert report["metrics"]["top_n_ordering_correctness"]["rate"] == 1.0
    assert report["metrics"]["hallucination_fail_closed_violation_count"] == 0
    assert report["metrics"]["generation_validation_fallback_count"] == 0
    assert report["failures"] == []
    assert report["result_validation_summary"] == {
        "EVALUATED": 19,
        "NO_DETERMINISTIC_EXPECTATION": 21,
    }


def test_every_result_case_has_an_independent_live_oracle_contract() -> None:
    _, cases = load_dataset()

    for case in cases:
        oracle = _oracle_query(case)
        if case.expected_status in {"SUPPORTED", "NO_MATCH"}:
            assert oracle is not None, case.case_id
        else:
            assert oracle is None, case.case_id


def test_report_writer_preserves_simulation_disclaimer(tmp_path) -> None:
    report = run_benchmark(mode="simulation", use_hcx=False)
    json_path, markdown_path = write_report(report, tmp_path, date(2026, 8, 25))

    assert json_path.name == "baseline_simulation_20260825.json"
    assert markdown_path.name == "baseline_simulation_20260825.md"
    assert markdown_path.read_bytes().startswith(b"\xef\xbb\xbf")
    markdown = markdown_path.read_text(encoding="utf-8-sig")
    assert "Team evaluation benchmark only" in markdown
    assert "not official evaluation ground truth" in markdown


def test_simulation_and_live_reports_do_not_overwrite_each_other(tmp_path) -> None:
    simulation = run_benchmark(mode="simulation", use_hcx=False)
    live_shape = {**simulation, "benchmark_mode": "live", "live_data_used": True}

    simulation_paths = write_report(simulation, tmp_path, date(2026, 8, 25))
    live_paths = write_report(live_shape, tmp_path, date(2026, 8, 25))

    assert {path.name for path in (*simulation_paths, *live_paths)} == {
        "baseline_simulation_20260825.json",
        "baseline_simulation_20260825.md",
        "baseline_live_20260825.json",
        "baseline_live_20260825.md",
    }


def test_live_mode_requires_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        run_benchmark(mode="live", use_hcx=False)
