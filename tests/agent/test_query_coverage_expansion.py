"""End-to-end safety checks for the 2026-08-24 text-field expansion."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.contracts import QueryUnderstandingStatus, RouteHint
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.core.config import Settings
from app.main import create_app
from app.structured import (
    FilterOperator,
    StructuredFilter,
    StructuredQueryContract,
    StructuredQueryStatus,
    StructuredQueryValidationError,
)
from mappings.aliases.registry import _FIELD_ALIASES, normalize_alias_text
from mappings.core import get_confirmed_field_map
from mappings.semantic import get_semantic_field_approval


PREF02_BASE_INDEX_SENTINELS = (
    "Index is not provided by Management Company",
    "Index is not available on Lipper Database",
)


OPEN_TEXT_CASES = (
    ("국내채권", "상품코드", "PRBD01N001", "prbd.product_code", "BOND001"),
    ("국내채권", "상품명", "PRBD01N001", "prbd.product_name", "국고채권A"),
    (
        "국내채권",
        "상품중분류명",
        "PRBD01N001",
        "prbd.product_mid_category_name",
        "채권",
    ),
    (
        "국내채권",
        "상품소분류명",
        "PRBD01N001",
        "prbd.product_sub_category_name",
        "국채",
    ),
    (
        "국내 ETF",
        "운용사",
        "PREF01N001",
        "pref01.fund_manager_name",
        "미래에셋자산운용",
    ),
    (
        "국내 ETF",
        "기초지수",
        "PREF01N001",
        "pref01.base_index_name",
        "KOSPI 200",
    ),
    (
        "국내 ETF",
        "운용전략",
        "PREF01N001",
        "pref01.strategy_name",
        "패시브",
    ),
    (
        "해외 ETF",
        "상품명",
        "PREF02N001",
        "pref02.product_name",
        "Global Equity ETF",
    ),
    (
        "해외 ETF",
        "해외ETF RIC",
        "PREF02N001",
        "pref02.product_identifier",
        "GL001",
    ),
    (
        "해외 ETF",
        "운용사",
        "PREF02N001",
        "pref02.fund_manager_name",
        "Vanguard",
    ),
    (
        "해외 ETF",
        "기초지수",
        "PREF02N001",
        "pref02.base_index_name",
        "S&P 500",
    ),
    (
        "해외 ETF",
        "투자자산군",
        "PREF02N001",
        "pref02.investment_asset_type",
        "주식",
    ),
    (
        "해외 ETF",
        "투자지역",
        "PREF02N001",
        "pref02.investment_region",
        "미국",
    ),
    (
        "공모펀드",
        "벤치마크명",
        "PRFD01N001",
        "prfd.benchmark_name",
        "KOSPI",
    ),
    (
        "공모펀드",
        "클래스명",
        "PRFD01N001",
        "prfd.class_name",
        "A클래스",
    ),
    (
        "공모펀드",
        "클래스판매채널",
        "PRFD01N001",
        "prfd.class_sales_channel_name",
        "온라인",
    ),
    (
        "공모펀드",
        "제로인유형명",
        "PRFD01N001",
        "prfd.zero_in_type_name",
        "국내주식형",
    ),
)


class EmptyBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return ()


class RowsBackend(EmptyBackend):
    def __init__(self) -> None:
        super().__init__()
        self.rows: tuple[dict[str, object], ...] = ()

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return self.rows


def _expected_parameters(
    semantic_key: str,
    value: str,
) -> tuple[str, ...]:
    if semantic_key == "pref02.base_index_name":
        return (value, *PREF02_BASE_INDEX_SENTINELS)
    return (value,)


def _parse_and_ground(product: str, alias: str, value: str):
    parsed = QueryParser().parse(
        request_id="coverage-expansion",
        question_id="coverage-expansion",
        question=f"{product} 중 {alias}이 {value}인 상품",
    )
    return parsed, OntologyGrounder().ground(parsed)


@pytest.mark.parametrize(
    ("product", "alias", "table", "semantic_key", "value"),
    OPEN_TEXT_CASES,
)
def test_new_text_capabilities_parse_ground_compile_and_execute_no_match(
    product: str,
    alias: str,
    table: str,
    semantic_key: str,
    value: str,
) -> None:
    parsed, grounded = _parse_and_ground(product, alias, value)

    assert parsed.understanding is not None
    assert parsed.understanding.status is QueryUnderstandingStatus.PARSED
    assert parsed.understanding.semantic_keys == (semantic_key,)
    assert parsed.understanding.filter_conditions[0].value == value
    assert grounded.route_hint is RouteHint.STRUCTURED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.SUPPORTED
    assert grounded.structured_query is not None
    assert grounded.structured_query.product_scope == table
    assert grounded.structured_query.filters == (
        StructuredFilter(
            field=semantic_key,
            operator=FilterOperator.EQ,
            value=value,
        ),
    )

    backend = EmptyBackend()
    runtime = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    ).state.runtime
    compiled = runtime.structured_planner.compile(grounded.structured_query)

    assert " = %s" in compiled.sql
    assert compiled.parameters == _expected_parameters(semantic_key, value)
    if semantic_key == "pref02.base_index_name":
        assert " IS NOT NULL" in compiled.sql
        assert " NOT IN (%s, %s)" in compiled.sql
    result = asyncio.run(
        runtime.structured_executor.execute(grounded.structured_query)
    )
    assert result.status is StructuredQueryStatus.NO_MATCH
    assert len(backend.calls) == 1


@pytest.mark.parametrize(
    ("product", "alias", "table", "semantic_key", "value"),
    OPEN_TEXT_CASES,
)
def test_new_text_capabilities_approve_ne_but_keep_ordering_closed(
    product: str,
    alias: str,
    table: str,
    semantic_key: str,
    value: str,
) -> None:
    runtime = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=EmptyBackend(),
    ).state.runtime
    compiled = runtime.structured_planner.compile(
        StructuredQueryContract(
            product_scope=table,
            filters=(
                StructuredFilter(
                    field=semantic_key,
                    operator=FilterOperator.NE,
                    value=value,
                ),
            ),
            projections=(semantic_key,),
        )
    )
    assert " <> %s" in compiled.sql
    assert compiled.parameters == _expected_parameters(semantic_key, value)
    if semantic_key == "pref02.base_index_name":
        assert compiled.sql.count(" NOT IN (%s, %s)") == 1

    parsed = QueryParser().parse(
        request_id="coverage-sort-closed",
        question_id="coverage-sort-closed",
        question=f"{product} {alias} 높은 순 3개",
    )
    grounded = OntologyGrounder().ground(parsed)
    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == (
        "semantic_operation_not_open"
    )


@pytest.mark.parametrize(
    ("product", "alias", "table", "semantic_key", "value"),
    OPEN_TEXT_CASES,
)
def test_numeric_threshold_is_not_inferred_for_new_text_fields(
    product: str,
    alias: str,
    table: str,
    semantic_key: str,
    value: str,
) -> None:
    del table, semantic_key, value
    parsed = QueryParser().parse(
        request_id="coverage-range-closed",
        question_id="coverage-range-closed",
        question=f"{product} {alias} 10 이상",
    )
    grounded = OntologyGrounder().ground(parsed)

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == (
        "semantic_operation_not_open"
    )


def test_aliases_have_no_normalized_collision_within_a_product_scope() -> None:
    by_identity: dict[tuple[str, str], tuple[str, ...]] = {}
    for alias in _FIELD_ALIASES:
        identity = (alias.logical_table_id, normalize_alias_text(alias.alias))
        prior = by_identity.setdefault(identity, alias.semantic_keys)
        assert prior == alias.semantic_keys, identity


def test_core_and_g3_do_not_duplicate_the_same_source_field_authority() -> None:
    core = {
        (mapping.logical_table_id, mapping.qualified_name)
        for mapping in get_confirmed_field_map().values()
    }
    semantic = {
        (table, approval.qualified_name)
        for table in ("PRBD01N001", "PREF01N001", "PREF02N001", "PRFD01N001")
        for semantic_key in (
            "pref02.expense_ratio",
            "pref02.aum_latest",
            "pref02.product_identifier",
            "pref02.product_name",
            "prbd.pd_risk_gcd_unresolved",
            "prbd.dur_unresolved",
            "prbd.ndy_dur_unresolved",
            "prbd.cov_unresolved",
        )
        for approval in (get_semantic_field_approval(table, semantic_key),)
        if approval is not None
    }

    assert core.isdisjoint(semantic)


def test_raw_code_ordering_and_unapproved_date_sentinels_stay_closed() -> None:
    risk = QueryParser().parse(
        request_id="risk-order-closed",
        question_id="risk-order-closed",
        question="국내채권 위험등급 높은 순 3개",
    )
    grounded = OntologyGrounder().ground(risk)
    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == (
        "semantic_operation_not_open"
    )

    mapped_sources = {
        (mapping.logical_table_id, mapping.source_column)
        for mapping in get_confirmed_field_map().values()
    }
    assert {
        ("PRBD01N001", "crd_grd_dt"),
        ("PRBD01N001", "isu_dt"),
        ("PRBD01N001", "mat_dt"),
        ("PREF02N001", "pd_lstg_dt"),
    }.isdisjoint(mapped_sources)


@pytest.mark.parametrize("sentinel", PREF02_BASE_INDEX_SENTINELS)
@pytest.mark.parametrize("operator", (FilterOperator.EQ, FilterOperator.NE))
def test_pref02_base_index_sentinel_is_not_queryable_as_an_index_name(
    sentinel: str,
    operator: FilterOperator,
) -> None:
    parsed, grounded = _parse_and_ground("해외 ETF", "기초지수", sentinel)

    assert parsed.understanding is not None
    assert parsed.understanding.filter_conditions[0].value == sentinel
    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == (
        "semantic_null_equivalent_not_queryable"
    )

    runtime = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=EmptyBackend(),
    ).state.runtime
    with pytest.raises(
        StructuredQueryValidationError,
        match="null-equivalent source literal",
    ):
        runtime.structured_planner.compile(
            StructuredQueryContract(
                product_scope="PREF02N001",
                filters=(
                    StructuredFilter(
                        field="pref02.base_index_name",
                        operator=operator,
                        value=sentinel,
                    ),
                ),
                projections=("pref02.base_index_name",),
            )
        )


def test_pref02_base_index_project_drops_sentinels_before_answer_evidence() -> None:
    backend = RowsBackend()
    runtime = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    ).state.runtime
    query = StructuredQueryContract(
        product_scope="PREF02N001",
        projections=("pref02.base_index_name",),
    )
    compiled = runtime.structured_planner.compile(query)
    selection = compiled.projected_fields[0]
    qualified_name = selection.field.qualified_name
    runtime_field = runtime.g2_registry.field(
        "PREF02N001", "pref02.base_index_name"
    )

    assert runtime_field is not None
    assert runtime_field.null_equivalent_literals == (
        PREF02_BASE_INDEX_SENTINELS
    )
    assert runtime_field.source_literal_classification == (
        "SOURCE_NOT_AVAILABLE"
    )
    assert runtime_field.semantic_literal_classification == "NULL_EQUIVALENT"

    def row(source_row_id: str, value: str) -> dict[str, object]:
        return {
            "__source_row_id": source_row_id,
            "__logical_table_id": "PREF02N001",
            "__raw_record": {
                qualified_name: {"type": "STRING", "value": value}
            },
            "__parse_statuses": {qualified_name: "OK"},
            selection.value_alias: value,
        }

    backend.rows = (
        row("srid:v1:sentinel-management", PREF02_BASE_INDEX_SENTINELS[0]),
        row("srid:v1:actual", "S&P 500"),
        row("srid:v1:sentinel-lipper", PREF02_BASE_INDEX_SENTINELS[1]),
    )

    result = asyncio.run(runtime.structured_executor.execute(query))

    assert compiled.parameters == PREF02_BASE_INDEX_SENTINELS
    assert " IS NOT NULL" in compiled.sql
    assert " NOT IN (%s, %s)" in compiled.sql
    assert result.candidates == (
        {"pref02.base_index_name": "S&P 500"},
    )
    assert len(result.evidence) == 1
    assert result.evidence[0].raw_value == "S&P 500"
    assert result.evidence[0].normalized_value == "S&P 500"
    assert all(
        sentinel not in repr((result.candidates, result.evidence))
        for sentinel in PREF02_BASE_INDEX_SENTINELS
    )
    # Defense-in-depth filtering must not rewrite the backend/raw fixture.
    assert backend.rows[0][selection.value_alias] == (
        PREF02_BASE_INDEX_SENTINELS[0]
    )
