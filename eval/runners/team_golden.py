"""Single-turn team golden-query evaluation simulation.

The default mode uses deterministic, schema-shaped fixtures and deterministic
generation. It measures the real parser, grounder, planner, evidence validator,
renderer, and GET /answer contract without claiming official ground truth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any

from fastapi.testclient import TestClient

from app.agent.contracts import QueryContract, RouteHint
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.agent.router import QueryRouter
from app.core.constants import NO_EVIDENCE_CONTEXT
from app.core.config import Settings
from app.generation import AnswerGenerator, GenerationInput, GenerationResult, HyperClovaAnswerGenerator
from app.llm import build_hcx_client
from app.main import create_app
from app.structured import AggregateFunction, FilterOperator, SortDirection
from app.structured.contracts import StructuredFilter, StructuredQueryContract, StructuredSort
from eval.error_taxonomy import FailureType
from mappings.semantic import get_default_projection_keys, get_semantic_field_approval
from pipeline.normalize.models import TargetType


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "eval" / "datasets" / "team_golden_queries_v1.json"
ANSWER_FIELDS = {"question_id", "question", "retrieved_context", "think_trace", "answer"}


@dataclass(frozen=True, slots=True)
class GoldenCase:
    case_id: str
    product_family: str
    query_type: str
    question: str
    expected_status: str
    expected_product_scope: str | None
    expected_semantic_keys: tuple[str, ...]
    expected_operation: tuple[str, ...]
    expected_result_count: int | None
    expected_identifiers: tuple[str, ...]
    expected_filter_values: tuple[str, ...]
    expected_limit: int | None
    fixture_mode: str
    rationale: str
    evidence_basis: str


def load_dataset(path: Path = DEFAULT_DATASET) -> tuple[dict[str, Any], tuple[GoldenCase, ...]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("official_ground_truth") is not False:
        raise ValueError("team dataset must explicitly deny official ground-truth status")
    cases = tuple(
        GoldenCase(
            **{
                **record,
                "expected_semantic_keys": tuple(record["expected_semantic_keys"]),
                "expected_operation": tuple(record["expected_operation"]),
                "expected_identifiers": tuple(record["expected_identifiers"]),
                "expected_filter_values": tuple(
                    record.get("expected_filter_values", ())
                ),
                "expected_limit": record.get("expected_limit"),
            }
        )
        for record in document["cases"]
    )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("case_id values must be unique")
    return document, cases


SIMULATED_ROWS: dict[str, tuple[dict[str, str], ...]] = {
    "PRBD01N001": tuple({"__id": f"BOND{index:03d}"} for index in range(1, 5)),
    "PREF01N001": (
        {"__id":"KR001","pref01.product_code":"069500","pref01.product_name":"KODEX 200","pref01.listed_share_count":"500","pref01.aum_latest":"400"},
        {"__id":"KR002","pref01.product_code":"102110","pref01.product_name":"TIGER 200","pref01.listed_share_count":"300","pref01.aum_latest":"300"},
        {"__id":"KR003","pref01.product_code":"114800","pref01.product_name":"KODEX 인버스","pref01.listed_share_count":"100","pref01.aum_latest":"200"},
        {"__id":"KR004","pref01.product_code":"123310","pref01.product_name":"TIGER 인버스","pref01.listed_share_count":"50","pref01.aum_latest":"100"},
    ),
    "PREF02N001": (
        {"__id":"GL001","pref02.product_identifier":"GL001","pref02.product_name":"해외 ETF Alpha","pref02.aum_latest":"400"},
        {"__id":"GL002","pref02.product_identifier":"GL002","pref02.product_name":"해외 ETF Beta","pref02.aum_latest":"300"},
        {"__id":"GL003","pref02.product_identifier":"GL003","pref02.product_name":"해외 ETF Gamma","pref02.aum_latest":"200"},
        {"__id":"GL004","pref02.product_identifier":"GL004","pref02.product_name":"해외 ETF Delta","pref02.aum_latest":"100"},
    ),
    "PRFD01N001": (
        {"__id":"FUND001","prfd.product_code":"F001","prfd.product_name":"글로벌성장펀드","prfd.net_assets":"400"},
        {"__id":"FUND002","prfd.product_code":"F002","prfd.product_name":"국내가치펀드","prfd.net_assets":"300"},
        {"__id":"FUND003","prfd.product_code":"F003","prfd.product_name":"채권혼합펀드","prfd.net_assets":"200"},
        {"__id":"FUND004","prfd.product_code":"F004","prfd.product_name":"단기채권펀드","prfd.net_assets":"100"},
    ),
}


def _typed(value: str, target_type: TargetType) -> Any:
    if target_type is TargetType.DECIMAL:
        return Decimal(value)
    if target_type is TargetType.INTEGER:
        return int(value)
    return value


def _raw_type(target_type: TargetType) -> str:
    return {
        TargetType.TEXT: "STRING",
        TargetType.DECIMAL: "DECIMAL",
        TargetType.INTEGER: "INTEGER",
        TargetType.DATE: "DATE",
        TargetType.TIMESTAMP: "DATETIME",
    }[target_type]


def _comparison(left: Any, operator: FilterOperator, right: Any) -> bool:
    return {
        FilterOperator.EQ: left == right,
        FilterOperator.NE: left != right,
        FilterOperator.LT: left < right,
        FilterOperator.LE: left <= right,
        FilterOperator.GT: left > right,
        FilterOperator.GE: left >= right,
    }[operator]


class SimulationBackend:
    def __init__(self) -> None:
        self.rows: tuple[Mapping[str, Any], ...] = ()
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def configure(self, query: QueryContract | None, compiled: Any, fixture_mode: str) -> None:
        self.calls = []
        if query is None or compiled is None or fixture_mode == "EMPTY":
            self.rows = ()
            return
        source = list(SIMULATED_ROWS[query.product_scope])
        selections = {item.field.semantic_key: item for item in compiled.evidence_fields}
        for clause in query.filters:
            selection = selections[clause.field]
            expected = _typed(str(clause.value), selection.field.target_type)
            source = [
                row for row in source
                if _comparison(
                    _typed(row[clause.field], selection.field.target_type),
                    clause.operator,
                    expected,
                )
            ]
        if query.sort is not None:
            selection = selections[query.sort.field]
            source.sort(
                key=lambda row: _typed(row[query.sort.field], selection.field.target_type),
                reverse=query.sort.direction is SortDirection.DESC,
            )
        if query.limit is not None:
            source = source[: query.limit]
        if query.aggregate is AggregateFunction.COUNT:
            self.rows = ({"__count": len(source)},)
            return
        result: list[Mapping[str, Any]] = []
        for row in source:
            raw_record: dict[str, Any] = {}
            parse_statuses: dict[str, str] = {}
            record: dict[str, Any] = {
                "__source_row_id": f"srid:v1:eval-{query.product_scope}-{row['__id']}",
                "__logical_table_id": query.product_scope,
                "__raw_record": raw_record,
                "__parse_statuses": parse_statuses,
            }
            for selection in compiled.evidence_fields:
                key = selection.field.semantic_key
                value = row[key]
                raw_record[selection.field.qualified_name] = {
                    "type": _raw_type(selection.field.target_type),
                    "value": value,
                }
                parse_statuses[selection.field.qualified_name] = "OK"
                record[selection.value_alias] = _typed(value, selection.field.target_type)
            result.append(record)
        self.rows = tuple(result)

    async def fetch_all(self, sql: str, parameters: Sequence[Any]) -> Sequence[Mapping[str, Any]]:
        self.calls.append((sql, tuple(parameters)))
        return self.rows


class RecordingGenerator:
    def __init__(self, delegate: AnswerGenerator) -> None:
        self.delegate = delegate
        self.results: list[GenerationResult] = []

    async def generate(self, generation_input: GenerationInput) -> GenerationResult:
        result = await self.delegate.generate(generation_input)
        self.results.append(result)
        return result


class RecordingToolExecutor:
    """Benchmark observer around the production executor; it does not alter results."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.results: list[tuple[Any, ...]] = []

    async def execute(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
        result = await self.delegate.execute(*args, **kwargs)
        self.results.append(result)
        return result


@dataclass(frozen=True, slots=True)
class OracleOutcome:
    status: str
    result_count: int
    source_row_ids: tuple[str, ...]
    basis: str = "LIVE_POSTGRESQL_STRUCTURED_ORACLE"


def _oracle_query(case: GoldenCase) -> StructuredQueryContract | None:
    if case.expected_status not in {"SUPPORTED", "NO_MATCH"}:
        return None
    if "COUNT" in case.expected_operation:
        return StructuredQueryContract(
            product_scope=case.expected_product_scope or "",
            aggregate=AggregateFunction.COUNT,
        )
    if not case.expected_semantic_keys:
        return None
    semantic_key = case.expected_semantic_keys[0]
    filter_operations = tuple(
        operation
        for operation in case.expected_operation
        if operation in {item.value for item in FilterOperator}
    )
    if len(filter_operations) != len(case.expected_filter_values):
        return None
    filters = tuple(
        StructuredFilter(
            field=semantic_key,
            operator=FilterOperator(operation),
            value=value,
        )
        for operation, value in zip(
            filter_operations,
            case.expected_filter_values,
            strict=True,
        )
    )
    sort_operation = next(
        (
            operation
            for operation in case.expected_operation
            if operation.startswith("SORT_")
        ),
        None,
    )
    sort = (
        StructuredSort(
            field=semantic_key,
            direction=SortDirection(sort_operation.removeprefix("SORT_")),
        )
        if sort_operation is not None
        else None
    )
    table = case.expected_product_scope or ""
    projections = (
        get_default_projection_keys(table, semantic_key)
        if get_semantic_field_approval(table, semantic_key) is not None
        else (semantic_key,)
    )
    return StructuredQueryContract(
        product_scope=table,
        filters=filters,
        projections=projections,
        sort=sort,
        limit=case.expected_limit,
    )


def _source_row_ids(evidence: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.source_row_id for item in evidence))


def _oracle_outcome(executor: Any, case: GoldenCase) -> tuple[OracleOutcome | None, str | None]:
    query = _oracle_query(case)
    if query is None:
        return None, "UNSUPPORTED_CASE_HAS_NO_RESULT_SET"
    try:
        result = asyncio.run(executor.execute(query))
    except Exception:
        return None, "LIVE_ORACLE_EXECUTION_FAILED"
    if query.aggregate is AggregateFunction.COUNT:
        if len(result.aggregate_evidence) != 1:
            return None, "LIVE_ORACLE_AGGREGATE_INVALID"
        return (
            OracleOutcome(
                status="SUPPORTED",
                result_count=result.aggregate_evidence[0].value,
                source_row_ids=(),
            ),
            None,
        )
    source_row_ids = _source_row_ids(result.evidence)
    return (
        OracleOutcome(
            status=("SUPPORTED" if result.candidates else "NO_MATCH"),
            result_count=len(result.candidates),
            source_row_ids=source_row_ids,
        ),
        None,
    )


def _operations(query: QueryContract) -> tuple[str, ...]:
    understanding = query.understanding
    if understanding is None:
        return ()
    operations = [condition.operator.value for condition in understanding.filter_conditions]
    if understanding.sort_direction is not None:
        operations.append(f"SORT_{understanding.sort_direction.value}")
    if understanding.aggregate is AggregateFunction.COUNT:
        operations.append("COUNT")
    return tuple(operations)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 3)


def _ratio(passed: int, total: int) -> dict[str, Any]:
    return {"passed": passed, "evaluated": total, "rate": round(passed / total, 4) if total else None}


def _evidence_valid(expected_status: str, context: dict[str, Any]) -> bool:
    evidence = context.get("evidence", [])
    if expected_status == "SUPPORTED":
        aggregates = context.get("aggregate_evidence", [])
        row_valid = bool(evidence) and all(
            item.get("decision") == "SUPPORTED"
            and item.get("source_table")
            and item.get("source_row_id")
            and item.get("source_field")
            for item in evidence
        )
        aggregate_valid = bool(aggregates) and all(
            item.get("decision") == "SUPPORTED"
            and item.get("source_table")
            and item.get("operation") == "COUNT"
            and isinstance(item.get("value"), int)
            and item["value"] >= 0
            for item in aggregates
        )
        return row_valid != aggregate_valid
    if expected_status == "NO_MATCH":
        return context.get("status") == "NO_MATCH" and not evidence
    return context.get("status") == "UNSUPPORTED" and not evidence


def _row_count(context: dict[str, Any]) -> int | None:
    if context.get("status") == "NO_MATCH":
        return 0
    aggregates = context.get("aggregate_evidence")
    if isinstance(aggregates, list) and len(aggregates) == 1:
        value = aggregates[0].get("value")
        return value if isinstance(value, int) else None
    row_count = context.get("row_count")
    if isinstance(row_count, int):
        return row_count
    evidence = context.get("evidence")
    if not isinstance(evidence, list):
        return None
    return len({item.get("source_row_id") for item in evidence})


def _ordered_identifiers(context: dict[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    for item in context.get("evidence", []):
        value = item.get("product_key")
        if isinstance(value, str) and value not in result:
            result.append(value)
    return tuple(result)


def _tool_result_facts(results: tuple[Any, ...]) -> tuple[int | None, tuple[str, ...], tuple[str, ...]]:
    if len(results) != 1 or results[0].error_code is not None:
        return (0 if results and results[0].error_code is not None else None), (), ()
    result = results[0]
    if result.aggregate_evidence:
        return result.aggregate_evidence[0].value, (), ()
    source_row_ids = _source_row_ids(result.evidence)
    product_keys = tuple(dict.fromkeys(item.product_key for item in result.evidence))
    return len(result.candidates), source_row_ids, product_keys


def _ordering_valid(case: GoldenCase, grounded: QueryContract, context: dict[str, Any]) -> bool | None:
    if case.expected_status != "SUPPORTED" or not any(
        operation.startswith("SORT_") for operation in case.expected_operation
    ):
        return None
    plan = grounded.structured_query
    if plan is None or plan.sort is None or context.get("status") != "SUPPORTED":
        return False
    semantic_key = plan.sort.field
    values_by_row: dict[str, Decimal | str] = {}
    for item in context.get("evidence", []):
        if item.get("source_row_id") in values_by_row:
            continue
        source_field = item.get("source_field")
        if semantic_key.split(".")[-1] in {"aum_latest", "listed_share_count", "net_assets"}:
            suffix = {"aum_latest":"du_last_aum#1", "listed_share_count":"pd_lst_stk_cnt#1", "net_assets":"fd_nast_suma#1"}[semantic_key.split(".")[-1]]
            if source_field != suffix:
                continue
            values_by_row[item["source_row_id"]] = Decimal(str(item["normalized_value"]))
    values = list(values_by_row.values())
    if not values:
        return False
    return values == sorted(values, reverse=plan.sort.direction is SortDirection.DESC)


def _failure_types(checks: dict[str, bool | None], expected: str, actual: str) -> tuple[str, ...]:
    failures: list[FailureType] = []
    if not checks["answer_schema_valid"]:
        failures.append(FailureType.PARSE_ERROR)
    if not checks["product_scope_correct"]:
        failures.append(FailureType.PRODUCT_SCOPE_ERROR)
    if not checks["semantic_grounding_correct"]:
        failures.append(FailureType.SEMANTIC_GROUNDING_ERROR)
    if not checks["operation_correct"]:
        failures.append(FailureType.OPERATION_ERROR)
    if expected == "UNSUPPORTED" and actual != "UNSUPPORTED":
        failures.append(FailureType.UNSUPPORTED_FALSE_POSITIVE)
    if expected != "UNSUPPORTED" and actual == "UNSUPPORTED":
        failures.append(FailureType.UNSUPPORTED_FALSE_NEGATIVE)
    if expected == "NO_MATCH" and actual != "NO_MATCH":
        failures.append(FailureType.NO_MATCH_ERROR)
    if checks["result_correct"] is False:
        failures.append(FailureType.RESULT_MISMATCH)
    if checks["ordering_correct"] is False:
        failures.append(FailureType.ORDERING_ERROR)
    if not checks["evidence_valid"]:
        failures.append(FailureType.EVIDENCE_ERROR)
    if actual == "TOOL_FAILURE":
        failures.append(FailureType.TOOL_FAILURE)
    return tuple(dict.fromkeys(item.value for item in failures))


def run_benchmark(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    mode: str = "simulation",
    use_hcx: bool = False,
) -> dict[str, Any]:
    document, cases = load_dataset(dataset_path)
    if mode not in {"simulation", "live"}:
        raise ValueError("mode must be simulation or live")
    database_url = os.getenv("DATABASE_URL")
    if mode == "live" and not database_url:
        raise RuntimeError("DATABASE_URL is required for live benchmark mode")

    settings = Settings(
        _env_file=None,
        database_url=(database_url if mode == "live" else None),
        hcx_enabled=use_hcx,
    )
    generator: RecordingGenerator | None = None
    if use_hcx:
        if not settings.hcx_ready:
            raise RuntimeError("HCX_ENABLED/API key/API URL are required for optional HCX mode")
        generator = RecordingGenerator(HyperClovaAnswerGenerator(build_hcx_client(settings)))
    backend = SimulationBackend() if mode == "simulation" else None
    application = create_app(
        settings=settings,
        structured_backend=backend,
        answer_generator=generator,
    )
    runtime = application.state.runtime
    recording_tools = RecordingToolExecutor(runtime.tool_executor)
    application.state.runtime = replace(runtime, tool_executor=recording_tools)
    parser = QueryParser()
    grounder = OntologyGrounder()
    router = QueryRouter()
    results: list[dict[str, Any]] = []

    with TestClient(application, raise_server_exceptions=False) as client:
        for case in cases:
            oracle: OracleOutcome | None = None
            oracle_reason: str | None = None
            if mode == "live":
                oracle, oracle_reason = _oracle_outcome(
                    runtime.structured_executor,
                    case,
                )
            expected_status = (
                oracle.status if oracle is not None else case.expected_status
            )
            expected_count = (
                oracle.result_count
                if oracle is not None
                else case.expected_result_count
            )
            parsed = parser.parse(request_id=f"eval-{case.case_id}", question_id=case.case_id, question=case.question)
            grounded = grounder.ground(parsed)
            route = router.route(grounded)
            if backend is not None:
                plan = grounded.structured_query
                compiled = application.state.runtime.structured_planner.compile(plan) if plan is not None else None
                backend.configure(plan, compiled, case.fixture_mode)
            generation_start = len(generator.results) if generator is not None else 0
            tool_start = len(recording_tools.results)
            started = monotonic()
            response = client.get("/answer", params={"question_id": case.case_id, "question": case.question})
            elapsed_ms = (monotonic() - started) * 1000
            try:
                payload = response.json()
            except Exception:
                payload = {}
            schema_valid = response.status_code == 200 and set(payload) == ANSWER_FIELDS and all(isinstance(value, str) for value in payload.values())
            try:
                context = json.loads(payload.get("retrieved_context", "")) if schema_valid else {}
            except json.JSONDecodeError:
                context = (
                    {"status": "UNSUPPORTED", "evidence": []}
                    if payload.get("retrieved_context") == NO_EVIDENCE_CONTEXT
                    else {}
                )
            actual_status = str(context.get("status", "PARSE_ERROR"))
            understanding = grounded.understanding
            actual_scope = understanding.logical_table_id if understanding is not None else None
            actual_keys = tuple(understanding.semantic_keys) if understanding is not None else ()
            actual_ops = _operations(grounded)
            expected_route = RouteHint.STRUCTURED if expected_status in {"SUPPORTED", "NO_MATCH"} else RouteHint.UNSUPPORTED
            observed_tool_results = (
                recording_tools.results[-1]
                if len(recording_tools.results) > tool_start
                else ()
            )
            tool_count, actual_source_ids, actual_product_keys = _tool_result_facts(
                observed_tool_results
            )
            actual_count = tool_count if tool_count is not None else _row_count(context)
            if mode == "simulation" and case.expected_result_count is not None:
                result_evaluated = True
                result_reason = None
                result_basis = "DETERMINISTIC_SIMULATION_FIXTURE"
                result_correct = (
                    actual_count == case.expected_result_count
                    and (
                        not case.expected_identifiers
                        or actual_product_keys == case.expected_identifiers
                    )
                )
            elif mode == "live" and oracle is not None:
                result_evaluated = True
                result_reason = None
                result_basis = oracle.basis
                identity_correct = (
                    True
                    if "COUNT" in case.expected_operation
                    else set(actual_source_ids) == set(oracle.source_row_ids)
                )
                result_correct = (
                    actual_count == oracle.result_count and identity_correct
                )
            else:
                result_evaluated = False
                result_reason = oracle_reason or "NO_DETERMINISTIC_EXPECTATION"
                result_basis = None
                result_correct = None
            if (
                mode == "live"
                and oracle is not None
                and oracle.status == "SUPPORTED"
                and any(
                    operation.startswith("SORT_")
                    for operation in case.expected_operation
                )
            ):
                ordering = actual_source_ids == oracle.source_row_ids
            elif mode == "live":
                ordering = None
            else:
                ordering = _ordering_valid(case, grounded, context)
            backend_calls = len(backend.calls) if backend is not None else None
            hallucination_violation = expected_status == "UNSUPPORTED" and (
                actual_status == "SUPPORTED" or (backend_calls is not None and backend_calls > 0)
            )
            checks: dict[str, bool | None] = {
                "routing_correct": route is expected_route,
                "status_correct": actual_status == expected_status,
                "product_scope_correct": actual_scope == case.expected_product_scope,
                "semantic_grounding_correct": actual_keys == case.expected_semantic_keys,
                "operation_correct": actual_ops == case.expected_operation,
                "result_correct": result_correct,
                "ordering_correct": ordering,
                "answer_schema_valid": schema_valid,
                "evidence_valid": _evidence_valid(expected_status, context),
                "hallucination_fail_closed": not hallucination_violation,
            }
            fallback = False
            if generator is not None and len(generator.results) > generation_start:
                fallback = generator.results[-1].used_fallback
            failures = list(_failure_types(checks, expected_status, actual_status))
            if fallback:
                failures.append(FailureType.GENERATION_VALIDATION_FALLBACK.value)
            required_checks = [value for value in checks.values() if value is not None]
            results.append({
                "case_id": case.case_id,
                "product_family": case.product_family,
                "query_type": case.query_type,
                "question": case.question,
                "dataset_expected_status": case.expected_status,
                "expected_status": expected_status,
                "expected_status_source": (
                    oracle.basis if oracle is not None else "DATASET_METADATA"
                ),
                "actual_status": actual_status,
                "expected_product_scope": case.expected_product_scope,
                "actual_product_scope": actual_scope,
                "expected_semantic_keys": list(case.expected_semantic_keys),
                "actual_semantic_keys": list(actual_keys),
                "expected_operation": list(case.expected_operation),
                "actual_operation": list(actual_ops),
                "expected_result_count": expected_count,
                "actual_result_count": actual_count,
                "result_validation": {
                    "evaluated": result_evaluated,
                    "basis": result_basis,
                    "reason": result_reason,
                },
                "checks": checks,
                "passed": all(required_checks) and not fallback,
                "failure_types": failures,
                "backend_call_count": backend_calls,
                "generation_fallback": fallback,
                "latency_ms": round(elapsed_ms, 3),
                "rationale": case.rationale,
                "evidence_basis": case.evidence_basis,
            })

    def metric(check: str) -> dict[str, Any]:
        values = [result["checks"][check] for result in results if result["checks"][check] is not None]
        return _ratio(sum(value is True for value in values), len(values))

    latencies = [result["latency_ms"] for result in results]
    passed = sum(result["passed"] for result in results)
    failures = [result for result in results if not result["passed"]]
    failure_counts = Counter(kind for result in failures for kind in result["failure_types"])
    validation_reasons = Counter(
        result["result_validation"]["reason"] or "EVALUATED"
        for result in results
    )
    expectation_variations = [
        {
            "case_id": result["case_id"],
            "dataset_expected_status": result["dataset_expected_status"],
            "live_expected_status": result["expected_status"],
        }
        for result in results
        if result["dataset_expected_status"] != result["expected_status"]
    ]
    category_rates: dict[str, dict[str, Any]] = {}
    for family in sorted({case.product_family for case in cases}):
        family_results = [result for result in results if result["product_family"] == family]
        category_rates[family] = _ratio(sum(result["passed"] for result in family_results), len(family_results))
    type_rates: dict[str, dict[str, Any]] = {}
    for query_type in sorted({case.query_type for case in cases}):
        selected = [result for result in results if result["query_type"] == query_type]
        type_rates[query_type] = _ratio(sum(result["passed"] for result in selected), len(selected))

    return {
        "dataset_name": document["dataset_name"],
        "dataset_kind": document["dataset_kind"],
        "official_ground_truth": False,
        "source_snapshot": document["source_snapshot"],
        "benchmark_mode": mode,
        "live_data_used": mode == "live",
        "generation_mode": "hyperclova_x_optional" if use_hcx else "deterministic",
        "case_count": len(results),
        "overall": _ratio(passed, len(results)),
        "metrics": {
            "routing_accuracy": metric("routing_correct"),
            "support_status_accuracy": metric("status_correct"),
            "semantic_grounding_accuracy": metric("semantic_grounding_correct"),
            "operation_accuracy": metric("operation_correct"),
            "result_set_correctness": metric("result_correct"),
            "top_n_ordering_correctness": metric("ordering_correct"),
            "answer_schema_validity": metric("answer_schema_valid"),
            "evidence_validity": metric("evidence_valid"),
            "hallucination_fail_closed_violation_count": sum(not result["checks"]["hallucination_fail_closed"] for result in results),
            "generation_validation_fallback_count": sum(result["generation_fallback"] for result in results),
            "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        },
        "category_pass_rates": category_rates,
        "query_type_pass_rates": type_rates,
        "failure_distribution": dict(failure_counts.most_common()),
        "result_validation_summary": dict(validation_reasons),
        "dataset_expectation_variations": expectation_variations,
        "failures": failures,
        "cases": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]

    def percentage(metric: dict[str, Any]) -> str:
        rate = metric["rate"]
        return "N/A" if rate is None else f"{rate:.1%}"

    lines = [
        f"# Team Golden Query baseline — {report['source_snapshot']}",
        "",
        "> Team evaluation benchmark only. This is not official evaluation ground truth.",
        "",
        f"- Mode: `{report['benchmark_mode']}`",
        f"- Live staging used: `{report['live_data_used']}`",
        f"- Generation: `{report['generation_mode']}`",
        f"- Cases: {report['case_count']}",
        f"- Exact case pass: {report['overall']['passed']}/{report['overall']['evaluated']} ({report['overall']['rate']:.1%})",
        f"- Routing accuracy: {percentage(metrics['routing_accuracy'])}",
        f"- Status accuracy: {percentage(metrics['support_status_accuracy'])}",
        f"- Semantic grounding accuracy: {percentage(metrics['semantic_grounding_accuracy'])}",
        f"- Operation accuracy: {percentage(metrics['operation_accuracy'])}",
        f"- Result correctness: {percentage(metrics['result_set_correctness'])}",
        f"- Ordering correctness: {percentage(metrics['top_n_ordering_correctness'])}",
        f"- Evidence validity: {percentage(metrics['evidence_validity'])}",
        f"- Answer schema validity: {percentage(metrics['answer_schema_validity'])}",
        f"- Fail-closed violations: {metrics['hallucination_fail_closed_violation_count']}",
        f"- Latency p50/p95: {metrics['latency_ms']['p50']}/{metrics['latency_ms']['p95']} ms",
        "",
        "## Product-family pass rate",
        "",
    ]
    for family, value in report["category_pass_rates"].items():
        lines.append(f"- {family}: {value['passed']}/{value['evaluated']} ({value['rate']:.1%})")
    lines.extend(("", "## Result validation coverage", ""))
    for reason, count in report["result_validation_summary"].items():
        lines.append(f"- {reason}: {count}")
    if report["dataset_expectation_variations"]:
        lines.extend(("", "## Dataset/live expectation variations", ""))
        for variation in report["dataset_expectation_variations"]:
            lines.append(
                f"- `{variation['case_id']}`: "
                f"{variation['dataset_expected_status']} → "
                f"{variation['live_expected_status']}"
            )
    lines.extend(("", "## Failure distribution", ""))
    for name, count in list(report["failure_distribution"].items())[:5]:
        lines.append(f"- {name}: {count}")
    lines.extend(("", "## Failed cases", ""))
    for result in report["failures"]:
        kinds = ", ".join(result["failure_types"]) or "EXACT_CASE_MISMATCH"
        lines.append(f"- `{result['case_id']}` [{kinds}] {result['question']}")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], report_dir: Path, report_date: date) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"baseline_{report['benchmark_mode']}_{report_date:%Y%m%d}"
    json_path = report_dir / f"{stem}.json"
    markdown_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8-sig")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=("simulation", "live"), default="simulation")
    parser.add_argument("--hcx", action="store_true", help="Opt in to credential-backed HCX generation")
    parser.add_argument("--report-dir", type=Path, default=REPO_ROOT / "eval" / "reports")
    args = parser.parse_args()
    report = run_benchmark(dataset_path=args.dataset, mode=args.mode, use_hcx=args.hcx)
    paths = write_report(report, args.report_dir, date.today())
    print(json.dumps({"status": "PASS", "reports": [str(path) for path in paths]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
