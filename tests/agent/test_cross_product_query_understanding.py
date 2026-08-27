"""Deterministic cross-product retrieval: parser/grounder understanding.

These tests exercise only the parser -> grounder boundary (mirroring
tests/agent/test_query_understanding.py's `_ground` helper) so they stay
independent of the HTTP `/answer` pipeline, the ToolExecutor, and the
StructuredToolAdapter, none of which this feature's minimum scope touches.
"""

from app.agent import QueryUnderstandingStatus, RouteHint
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.structured import AggregateFunction, StructuredQueryStatus


def _ground(question: str):
    parsed = QueryParser().parse(
        request_id="cross-product-request",
        question_id="cross-product-question",
        question=question,
    )
    return OntologyGrounder().ground(parsed)


def test_two_etf_scopes_count_is_supported_cross_product() -> None:
    grounded = _ground("국내 ETF와 해외 ETF 개수")

    assert grounded.route_hint is RouteHint.CROSS_PRODUCT
    assert grounded.cross_product is not None
    assert grounded.cross_product.status is QueryUnderstandingStatus.SUPPORTED
    assert grounded.cross_product.metric is AggregateFunction.COUNT
    assert {scope.logical_table_id for scope in grounded.cross_product.scopes} == {
        "PREF01N001",
        "PREF02N001",
    }
    assert len(grounded.cross_product.structured_queries) == 2
    scopes_by_table = {
        query.product_scope: query for query in grounded.cross_product.structured_queries
    }
    assert scopes_by_table["PREF01N001"].aggregate is AggregateFunction.COUNT
    assert scopes_by_table["PREF02N001"].aggregate is AggregateFunction.COUNT
    # Existing single-product understanding path is untouched by this branch.
    assert grounded.understanding is None
    assert grounded.structured_query is None


def test_domestic_etf_and_public_fund_count_is_supported_cross_product() -> None:
    grounded = _ground("국내 ETF와 공모펀드 개수")

    assert grounded.route_hint is RouteHint.CROSS_PRODUCT
    assert grounded.cross_product is not None
    assert grounded.cross_product.status is QueryUnderstandingStatus.SUPPORTED
    assert {scope.logical_table_id for scope in grounded.cross_product.scopes} == {
        "PREF01N001",
        "PRFD01N001",
    }


def test_field_specific_multi_product_question_stays_ambiguous_not_forced() -> None:
    """A field-specific cross-product question (not a bare COUNT intent)
    must not be force-merged -- per-field comparability across scopes is
    not established by this minimum-scope feature, so it falls through to
    the existing multiple_product_scopes AMBIGUOUS path unchanged."""

    grounded = _ground("국내 ETF와 해외 ETF 중 AUM이 큰 상품")

    assert grounded.cross_product is None
    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.AMBIGUOUS
    assert grounded.understanding.ambiguity == ("multiple_product_scopes",)


def test_field_specific_count_question_is_not_force_merged() -> None:
    """Even with an explicit COUNT token present, a question that also
    names a specific field (AUM) is field-specific, not a bare
    cross-product count -- it must not be merged."""

    grounded = _ground("국내 ETF와 해외 ETF 중 AUM이 큰 상품 개수")

    assert grounded.cross_product is None
    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.AMBIGUOUS


def test_scopeless_question_still_fails_closed_unchanged() -> None:
    """Existing scope-less behavior (no product alias matched at all) is
    untouched: this never reaches cross-product detection because fewer
    than two distinct product scopes were matched."""

    grounded = _ground("AUM이 큰 상품 3개")

    assert grounded.cross_product is None
    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.AMBIGUOUS
    assert grounded.understanding.ambiguity == ("product_scope_missing",)


def test_cross_product_structured_queries_reuse_closed_contract_type() -> None:
    grounded = _ground("국내 ETF와 해외 ETF 개수")

    assert grounded.cross_product is not None
    for query in grounded.cross_product.structured_queries:
        assert query.filters == ()
        assert query.sort is None
        assert query.limit is None
