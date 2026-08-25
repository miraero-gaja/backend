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
    assert document["source_snapshot"] == "2026-08-24"
    assert len(cases) > 0
    family_counts = Counter(case.product_family for case in cases)
    assert len(family_counts) > 1
    assert len(set(family_counts.values())) == 1, (
        "product families must carry an equal number of cases "
        f"(got {dict(family_counts)})"
    )
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
    """The deterministic simulation must fully pass against the CURRENT
    dataset and CURRENT runtime parser/grounder/semantic contract. This
    intentionally avoids pinning exact case counts or per-metric numbers --
    those are dataset-authoring details, not the property under test -- and
    instead asserts the generalized invariants: every evaluated case
    passes, every result-set/ordering check that was evaluated is 100%
    correct, no fail-closed violation or generation fallback occurred, and
    the dataset is explicitly the current (non-2026-07-11) snapshot.
    """

    _, cases = load_dataset()
    report = run_benchmark(mode="simulation", use_hcx=False)

    assert report["official_ground_truth"] is False
    assert report["benchmark_mode"] == "simulation"
    assert report["live_data_used"] is False
    assert report["generation_mode"] == "deterministic"
    assert report["source_snapshot"] == "2026-08-24"
    assert report["case_count"] == len(cases)

    assert report["overall"]["passed"] == report["overall"]["evaluated"]
    assert report["overall"]["rate"] == 1.0
    assert report["failures"] == []

    for metric_name in (
        "result_set_correctness",
        "top_n_ordering_correctness",
        "answer_schema_validity",
        "evidence_validity",
        "routing_accuracy",
        "support_status_accuracy",
        "semantic_grounding_accuracy",
        "operation_accuracy",
    ):
        metric = report["metrics"][metric_name]
        if metric["evaluated"]:
            assert metric["passed"] == metric["evaluated"], metric_name
            assert metric["rate"] == 1.0, metric_name

    assert report["metrics"]["hallucination_fail_closed_violation_count"] == 0
    assert report["metrics"]["generation_validation_fallback_count"] == 0

    # Every case's deterministic-simulation result-set expectation was
    # either evaluated against the fixture or explicitly deferred as
    # requiring a live oracle -- never silently skipped.
    validation_summary = report["result_validation_summary"]
    assert set(validation_summary) <= {"EVALUATED", "NO_DETERMINISTIC_EXPECTATION"}
    assert sum(validation_summary.values()) == report["case_count"]


def test_every_result_case_has_an_independent_live_oracle_contract() -> None:
    _, cases = load_dataset()

    for case in cases:
        oracle = _oracle_query(case)
        if case.expected_status in {"SUPPORTED", "NO_MATCH"}:
            assert oracle is not None, case.case_id
        else:
            assert oracle is None, case.case_id


def test_live_validation_required_cases_are_explicitly_tracked() -> None:
    """Cases whose result set can only be confirmed against a live
    PostgreSQL oracle (SUPPORTED/NO_MATCH cases with a result count) must
    not be silently assumed correct from a guessed number in simulation
    mode -- the runner defers them and the report records why.
    """

    _, cases = load_dataset()
    report = run_benchmark(mode="simulation", use_hcx=False)

    live_validation_required = {
        case.case_id
        for case in cases
        if case.expected_status in {"SUPPORTED", "NO_MATCH"}
    }
    unevaluated_despite_live_requirement = {
        result["case_id"]
        for result in report["cases"]
        if result["case_id"] in live_validation_required
        and not result["result_validation"]["evaluated"]
    }

    assert live_validation_required
    assert unevaluated_despite_live_requirement == set()
    for case_id in live_validation_required:
        result = next(r for r in report["cases"] if r["case_id"] == case_id)
        assert result["result_validation"]["basis"] == (
            "DETERMINISTIC_SIMULATION_FIXTURE"
        ), (
            f"{case_id}: simulation mode must resolve result sets from the "
            "deterministic fixture, not an unvalidated guess"
        )


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
