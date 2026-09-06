"""Fail-closed policy seams that do not add new retrieval structures."""

from app.agent import QueryUnderstandingStatus, RouteHint
from app.agent.cross_product_compat import (
    ETF_CONSTITUENT_RETURN_1Y,
    compatible_relation_scopes,
    is_cross_product_metric_compatible,
)
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.structured import AggregateFunction


def _ground(question: str):
    parsed = QueryParser().parse(
        request_id="policy-hardening",
        question_id="policy-hardening",
        question=question,
    )
    return OntologyGrounder().ground(parsed)


def test_constituent_etf_1y_compatibility_excludes_pref02() -> None:
    assert compatible_relation_scopes(
        ETF_CONSTITUENT_RETURN_1Y,
        ("PREF01N001", "PREF02N001"),
    ) == ("PREF01N001",)
    assert compatible_relation_scopes(
        ETF_CONSTITUENT_RETURN_1Y,
        ("PREF02N001",),
    ) == ()


def test_unknown_relation_metric_fails_closed_and_count_is_unchanged() -> None:
    assert compatible_relation_scopes(
        "etf.unapproved_metric",
        ("PREF01N001", "PREF02N001"),
    ) == ()
    assert is_cross_product_metric_compatible(AggregateFunction.COUNT) is True


def test_no_relation_runtime_means_etf_1y_question_stays_unsupported() -> None:
    grounded = _ground("국내 ETF와 해외 ETF 구성종목 기반 1년수익률")

    assert grounded.route_hint is RouteHint.UNSUPPORTED
    assert grounded.cross_product is None
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.AMBIGUOUS
    assert grounded.understanding.ambiguity == ("multiple_product_scopes",)


def test_cross_product_count_regression_keeps_both_etf_scopes() -> None:
    grounded = _ground("국내 ETF와 해외 ETF 개수")

    assert grounded.route_hint is RouteHint.CROSS_PRODUCT
    assert grounded.cross_product is not None
    assert {
        scope.logical_table_id for scope in grounded.cross_product.scopes
    } == {"PREF01N001", "PREF02N001"}
