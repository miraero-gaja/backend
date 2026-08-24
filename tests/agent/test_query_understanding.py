"""Deterministic natural-language grounding through the G2/G3 safety gates."""

import asyncio

import pytest

from app.agent import QueryUnderstandingStatus, RouteHint
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.core.config import Settings
from app.main import create_app
from app.structured import FilterOperator, SortDirection, StructuredQueryStatus


class EmptyBackend:
    def __init__(self) -> None:
        self.calls = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return ()


def _ground(question: str):
    parsed = QueryParser().parse(
        request_id="query-understanding-request",
        question_id="query-understanding-question",
        question=question,
    )
    return OntologyGrounder().ground(parsed)


def test_overseas_etf_aum_desc_top_n_is_supported() -> None:
    grounded = _ground("해외 ETF 중 AUM이 큰 상품 3개")

    assert grounded.route_hint is RouteHint.STRUCTURED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.SUPPORTED
    assert grounded.understanding.logical_table_id == "PREF02N001"
    assert grounded.understanding.semantic_keys == ("pref02.aum_latest",)
    assert grounded.structured_query is not None
    assert grounded.structured_query.sort is not None
    assert grounded.structured_query.sort.direction is SortDirection.DESC
    assert grounded.structured_query.projections == (
        "pref02.product_identifier",
        "pref02.product_name",
        "pref02.aum_latest",
    )
    assert grounded.structured_query.limit == 3
    assert grounded.understanding.execution_trace[-2:] == (
        "연산 승인: SORT_DESC",
        "Top-N 승인: 3",
    )


@pytest.mark.parametrize(
    "question",
    (
        "해외 ETF AUM 100억 이상",
        "해외 ETF 총보수 0.5% 이하",
    ),
)
def test_unapproved_financial_units_are_unsupported(question: str) -> None:
    grounded = _ground(question)

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.UNSUPPORTED
    assert grounded.understanding.unsupported_reason == (
        "unit_conversion_not_approved"
    )


@pytest.mark.parametrize(
    ("question", "reason"),
    (
        ("국내채권 위험등급 1 이하", "semantic_concept_not_confirmed"),
        (
            "국내채권 듀레이션 3 이하",
            "semantic_field_distinction_unapproved",
        ),
    ),
)
def test_prbd_unresolved_meanings_are_unsupported(
    question: str,
    reason: str,
) -> None:
    grounded = _ground(question)

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == reason


def test_confirmed_g2_field_filter_builds_deterministic_contract() -> None:
    grounded = _ground("국내 ETF 중 상품코드가 069500인 상품")

    assert grounded.route_hint is RouteHint.STRUCTURED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.SUPPORTED
    assert grounded.structured_query is not None
    assert grounded.structured_query.product_scope == "PREF01N001"
    assert grounded.structured_query.projections == ("pref01.product_code",)
    assert len(grounded.structured_query.filters) == 1
    condition = grounded.structured_query.filters[0]
    assert condition.field == "pref01.product_code"
    assert condition.operator is FilterOperator.EQ
    assert condition.value == "069500"


def test_confirmed_g2_source_native_range_builds_contract() -> None:
    grounded = _ground("국내 ETF 상장주식수 100 이상")

    assert grounded.route_hint is RouteHint.STRUCTURED
    assert grounded.structured_query is not None
    assert grounded.structured_query.projections == (
        "pref01.listed_share_count",
    )
    assert grounded.structured_query.filters[0].operator is FilterOperator.GE
    assert grounded.structured_query.filters[0].value == "100"


@pytest.mark.parametrize(
    ("word", "operator"),
    (
        ("이상", FilterOperator.GE),
        ("이하", FilterOperator.LE),
        ("초과", FilterOperator.GT),
        ("미만", FilterOperator.LT),
    ),
)
def test_range_words_are_parsed_deterministically(
    word: str,
    operator: FilterOperator,
) -> None:
    grounded = _ground(f"국내 ETF 상장주식수 100 {word}")

    assert grounded.structured_query is not None
    assert grounded.structured_query.filters[0].operator is operator


def test_filter_sort_and_top_n_combination_builds_one_contract() -> None:
    grounded = _ground(
        "국내 ETF 상장주식수 100 이상 높은 순 3개"
    )

    assert grounded.structured_query is not None
    assert grounded.structured_query.filters[0].operator is FilterOperator.GE
    assert grounded.structured_query.sort is not None
    assert grounded.structured_query.sort.direction is SortDirection.DESC
    assert grounded.structured_query.limit == 3


@pytest.mark.parametrize(
    ("question", "direction"),
    (
        ("국내 ETF AUM 내림차순", SortDirection.DESC),
        ("국내 ETF AUM 오름차순", SortDirection.ASC),
    ),
)
def test_explicit_sort_words_are_deterministic(
    question: str,
    direction: SortDirection,
) -> None:
    grounded = _ground(question)

    assert grounded.structured_query is not None
    assert grounded.structured_query.sort is not None
    assert grounded.structured_query.sort.direction is direction


def test_supported_contract_with_zero_rows_remains_no_match() -> None:
    grounded = _ground("해외 ETF 중 AUM이 큰 상품 3개")
    assert grounded.structured_query is not None
    backend = EmptyBackend()
    application = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    )

    result = asyncio.run(
        application.state.runtime.structured_executor.execute(
            grounded.structured_query
        )
    )

    assert result.status is StructuredQueryStatus.NO_MATCH
    assert result.candidates == ()
    assert len(backend.calls) == 1


def test_unknown_field_fails_closed() -> None:
    grounded = _ground("해외 ETF 변동성 높은 순 3개")

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == (
        "semantic_field_not_recognized"
    )


@pytest.mark.parametrize(
    "question",
    (
        "해외 ETF AUM Top 3",
        "해외 ETF AUM 상위 3개",
        "해외 ETF 중 AUM이 큰 상품 3개",
    ),
)
def test_explicit_top_n_patterns_have_deterministic_limit(question: str) -> None:
    grounded = _ground(question)

    assert grounded.structured_query is not None
    assert grounded.structured_query.limit == 3
    assert grounded.structured_query.sort is not None
    assert grounded.structured_query.sort.direction is SortDirection.DESC


def test_missing_product_scope_is_ambiguous_not_guessed() -> None:
    grounded = _ground("AUM이 큰 상품 3개")

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.AMBIGUOUS
    assert grounded.understanding.ambiguity == ("product_scope_missing",)


@pytest.mark.parametrize(
    ("question", "table"),
    (
        ("국내채권 개수", "PRBD01N001"),
        ("국내 ETF 개수", "PREF01N001"),
        ("해외 ETF 개수", "PREF02N001"),
        ("공모펀드 개수", "PRFD01N001"),
    ),
)
def test_explicit_product_groups_map_without_guessing(
    question: str,
    table: str,
) -> None:
    grounded = _ground(question)

    assert grounded.route_hint is RouteHint.STRUCTURED
    assert grounded.structured_query is not None
    assert grounded.structured_query.product_scope == table
    assert grounded.structured_query.aggregate is not None


def test_filtered_aggregation_is_fail_closed_until_supported() -> None:
    grounded = _ground("국내 ETF 상품코드 069500인 상품 개수")

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.structured_query is None
    assert grounded.understanding is not None
    assert grounded.understanding.unsupported_reason == (
        "filtered_aggregation_not_supported"
    )


def test_supported_explicit_patterns_need_no_assumption_status() -> None:
    grounded = _ground("해외 ETF 중 AUM이 큰 상품 3개")

    assert grounded.understanding is not None
    assert grounded.understanding.status is not (
        QueryUnderstandingStatus.RESOLVED_WITH_ASSUMPTION
    )
