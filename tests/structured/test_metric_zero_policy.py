"""2026-08-26 official query-time metric zero policy regressions."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.agent import QueryUnderstandingStatus, RouteHint
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.core.config import Settings
from app.main import create_app
from app.structured import (
    FilterOperator,
    SortDirection,
    StructuredFilter,
    StructuredQueryCompiler,
    StructuredQueryContract,
    StructuredQueryExecutor,
    StructuredQueryStatus,
    StructuredQueryValidationError,
    StructuredSort,
    TrustedField,
    TrustedQueryRegistry,
    TrustedTable,
)
from mappings.core import CORE_FIELD_MAPPINGS
from pipeline.normalize.models import TargetType


ZERO_POLICY_FIELDS = {
    ("PREF01N001", "pref01.return_1m", "du_er_1m"),
    ("PREF01N001", "pref01.return_3m", "du_er_3m"),
    ("PREF01N001", "pref01.return_1y", "du_er_1y"),
    ("PRFD01N001", "prfd.return_1m", "fd_mm1_ern_r"),
    ("PRFD01N001", "prfd.return_3m", "fd_mm3_ern_r"),
    ("PRFD01N001", "prfd.return_1y", "fd_yr1_ern_r"),
}


class EmptyBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return ()


class MetricReentryBackend(EmptyBackend):
    def __init__(self, value) -> None:
        super().__init__()
        self.value = value

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return ({"__value_000": self.value},)


class SignedMetricBackend(EmptyBackend):
    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return tuple(
            {
                "__source_row_id": f"row:{index}",
                "__logical_table_id": "PREF01N001",
                "__raw_record": {
                    "du_er_3m#1": {"type": "DECIMAL", "value": str(value)}
                },
                "__parse_statuses": {"du_er_3m#1": "OK"},
                "__value_000": value,
            }
            for index, value in enumerate(
                (Decimal("-1.25"), Decimal("2.50")),
                start=1,
            )
        )


def _ground(question: str):
    parsed = QueryParser().parse(
        request_id="metric-zero-policy",
        question_id="metric-zero-policy",
        question=question,
    )
    return OntologyGrounder().ground(parsed)


def _runtime(backend):
    return create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    ).state.runtime


def test_zero_policy_is_attached_only_to_the_six_open_return_metrics() -> None:
    actual = {
        (mapping.logical_table_id, mapping.semantic_field_key, mapping.source_column)
        for mapping in CORE_FIELD_MAPPINGS
        if mapping.zero_exclusion_policy is not None
    }

    assert actual == ZERO_POLICY_FIELDS
    for mapping in CORE_FIELD_MAPPINGS:
        if mapping.zero_exclusion_policy is not None:
            assert mapping.allowed_operations == ("SORT",)
            assert mapping.zero_exclusion_policy.criterion_operations == ("SORT",)


@pytest.mark.parametrize(
    ("question", "direction"),
    (
        ("국내 ETF 1개월수익률 높은 순 3개", SortDirection.DESC),
        ("국내 ETF 1개월수익률 낮은 순 3개", SortDirection.ASC),
        ("공모펀드 1년수익률 높은 순 3개", SortDirection.DESC),
        ("공모펀드 1년수익률 낮은 순 3개", SortDirection.ASC),
    ),
)
def test_return_sort_excludes_null_and_zero_in_sql_before_top_n(
    question: str,
    direction: SortDirection,
) -> None:
    grounded = _ground(question)

    assert grounded.route_hint is RouteHint.STRUCTURED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.SUPPORTED
    assert grounded.structured_query is not None
    assert grounded.structured_query.sort is not None
    assert grounded.structured_query.sort.direction is direction

    compiled = _runtime(EmptyBackend()).structured_planner.compile(
        grounded.structured_query
    )
    selection = compiled.zero_exclusion_fields[0]
    column = f'"{selection.field.physical_column}"'
    assert f"({column} IS NOT NULL AND {column} <> %s)" in compiled.sql
    assert compiled.sql.index("WHERE") < compiled.sql.index("ORDER BY")
    assert compiled.sql.index("ORDER BY") < compiled.sql.index("LIMIT %s")
    assert compiled.parameters == (Decimal("0"), 3)


def test_threshold_policy_is_candidate_stage_and_preserves_negative_positive() -> None:
    field = TrustedField(
        semantic_key="metric.return",
        logical_table_id="TEST01",
        source_column="metric",
        qualified_name="metric#1",
        physical_column="metric",
        target_type=TargetType.DECIMAL,
        allowed_operations=frozenset({"GT"}),
        zero_exclusion_operations=frozenset({"GT"}),
    )
    compiler = StructuredQueryCompiler(
        TrustedQueryRegistry(
            (TrustedTable("TEST01", "structured_staging", "stg_test01"),),
            (field,),
        )
    )
    compiled = compiler.compile(
        StructuredQueryContract(
            product_scope="TEST01",
            filters=(
                StructuredFilter(
                    field="metric.return",
                    operator=FilterOperator.GT,
                    value="-2",
                ),
            ),
            projections=("metric.return",),
        )
    )

    assert '"metric" > %s' in compiled.sql
    assert '("metric" IS NOT NULL AND "metric" <> %s)' in compiled.sql
    assert '"metric" > 0' not in compiled.sql
    assert compiled.parameters == (Decimal("-2"), Decimal("0"))


def test_closed_return_threshold_remains_unsupported() -> None:
    grounded = _ground("국내 ETF 1개월수익률이 0 이상")

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == "semantic_operation_not_open"


def test_projecting_zero_metric_under_another_criterion_does_not_delete_rows() -> None:
    runtime = _runtime(EmptyBackend())
    compiled = runtime.structured_planner.compile(
        StructuredQueryContract(
            product_scope="PREF01N001",
            projections=("pref01.return_1m",),
            sort=StructuredSort(
                field="pref01.listed_share_count",
                direction=SortDirection.DESC,
            ),
            limit=5,
        )
    )

    return_column = compiled.projected_fields[0].field.physical_column
    assert f'"{return_column}" <> %s' not in compiled.sql
    assert compiled.zero_exclusion_fields == ()
    assert compiled.parameters == (5,)


def test_all_zero_candidates_become_no_match_without_post_top_n_deletion() -> None:
    backend = EmptyBackend()
    runtime = _runtime(backend)
    grounded = _ground("국내 ETF 3개월수익률 높은 순 3개")
    assert grounded.structured_query is not None

    result = asyncio.run(runtime.structured_executor.execute(grounded.structured_query))

    assert result.status is StructuredQueryStatus.NO_MATCH
    assert len(backend.calls) == 1
    assert "<> %s" in backend.calls[0][0]


def test_negative_and_positive_metric_candidates_are_retained() -> None:
    backend = SignedMetricBackend()
    runtime = _runtime(backend)
    grounded = _ground("국내 ETF 3개월수익률 낮은 순 3개")
    assert grounded.structured_query is not None

    result = asyncio.run(runtime.structured_executor.execute(grounded.structured_query))

    assert result.status is StructuredQueryStatus.SUPPORTED
    assert result.candidates == (
        {"pref01.return_3m": "-1.25"},
        {"pref01.return_3m": "2.50"},
    )
    assert len(result.evidence) == 2


@pytest.mark.parametrize("value", (None, Decimal("0")))
def test_null_or_zero_cannot_reenter_from_a_stale_backend(value) -> None:
    backend = MetricReentryBackend(value)
    runtime = _runtime(backend)
    grounded = _ground("국내 ETF 3개월수익률 높은 순 3개")
    assert grounded.structured_query is not None

    with pytest.raises(
        StructuredQueryValidationError,
        match="null-or-zero metric re-entered structured evidence",
    ):
        asyncio.run(runtime.structured_executor.execute(grounded.structured_query))
