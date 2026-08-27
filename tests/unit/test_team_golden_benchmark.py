"""Deterministic regression checks for the team evaluation simulation."""

from collections import Counter
from datetime import date

import pytest

from app.structured import AggregateFunction
from eval.error_taxonomy import FailureType
from eval.runners.team_golden import (
    _cross_product_oracle_outcome,
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


class _FakeAggregateItem:
    def __init__(self, value: int) -> None:
        self.value = value


class _FakeStructuredResult:
    def __init__(self, value: int) -> None:
        self.aggregate_evidence = (_FakeAggregateItem(value),)


class _FakeStructuredExecutor:
    """Stands in for StructuredQueryExecutor so the cross-product live
    oracle can be tested without a real PostgreSQL connection."""

    def __init__(self, values_by_table: dict, fail_tables: frozenset = frozenset()) -> None:
        self._values = values_by_table
        self._fail_tables = fail_tables

    async def execute(self, query):
        if query.product_scope in self._fail_tables:
            raise RuntimeError(f"database unavailable for {query.product_scope}")
        return _FakeStructuredResult(self._values[query.product_scope])


def _cross_product_case(case_id: str = "etf-11"):
    _, cases = load_dataset()
    return next(case for case in cases if case.case_id == case_id)


def test_oracle_query_builds_one_independent_count_contract_per_scope() -> None:
    """The live oracle for a cross-product case must be built from
    independent per-scope COUNT contracts, mirroring how
    CrossProductQueryExecutor runs one StructuredQueryContract per scope
    rather than a single merged query."""

    case = _cross_product_case()
    queries = _oracle_query(case)

    assert isinstance(queries, tuple)
    assert len(queries) == len(case.expected_cross_product_counts)
    assert {query.product_scope for query in queries} == set(
        case.expected_cross_product_counts
    )
    assert all(query.aggregate is AggregateFunction.COUNT for query in queries)


def test_cross_product_oracle_reports_live_counts_per_scope_and_identity() -> None:
    case = _cross_product_case()
    executor = _FakeStructuredExecutor({"PREF01N001": 11, "PREF02N001": 22})

    outcome, reason = _cross_product_oracle_outcome(executor, case)

    assert reason is None
    assert outcome is not None
    assert outcome.status == "SUPPORTED"
    assert outcome.counts_by_table == {"PREF01N001": 11, "PREF02N001": 22}
    # Scope identity: exactly the two scopes this case is about, no more, no less.
    assert set(outcome.counts_by_table) == set(case.expected_cross_product_counts)


def test_cross_product_oracle_never_uses_the_simulation_fixture_values() -> None:
    """The live oracle must reflect the actual (fake) database response,
    not the deterministic simulation fixture's expected_cross_product_counts
    -- here the two are deliberately different so a bug that reused the
    fixture would be caught immediately."""

    case = _cross_product_case()
    live_values = {"PREF01N001": 999, "PREF02N001": 888}
    assert live_values != case.expected_cross_product_counts

    executor = _FakeStructuredExecutor(live_values)
    outcome, _ = _cross_product_oracle_outcome(executor, case)

    assert outcome.counts_by_table == live_values


def test_cross_product_oracle_is_unavailable_when_any_scope_query_fails() -> None:
    """Mirrors the single-product oracle's own philosophy: an oracle-side
    query failure makes the whole oracle unavailable (result_evaluated is
    False downstream) rather than being reinterpreted as an 'expected
    TOOL_FAILURE' golden value -- TOOL_FAILURE stays a purely actual-side
    runtime signal."""

    case = _cross_product_case()
    executor = _FakeStructuredExecutor(
        {"PREF01N001": 11, "PREF02N001": 22},
        fail_tables=frozenset({"PREF02N001"}),
    )

    outcome, reason = _cross_product_oracle_outcome(executor, case)

    assert outcome is None
    assert reason == "LIVE_ORACLE_EXECUTION_FAILED"


def test_non_cross_product_case_has_no_multi_scope_oracle() -> None:
    _, cases = load_dataset()
    single_product_case = next(
        case for case in cases if case.expected_cross_product_counts is None
        and case.expected_status == "SUPPORTED"
    )

    outcome, reason = _cross_product_oracle_outcome(
        _FakeStructuredExecutor({}), single_product_case
    )

    assert outcome is None
    assert reason == "CROSS_PRODUCT_CASE_HAS_NO_MULTI_SCOPE_ORACLE"
