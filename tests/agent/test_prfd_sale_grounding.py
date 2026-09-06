"""Deterministic PRFD sale/public-private phrase grounding regressions."""

from __future__ import annotations

import pytest

from app.agent import QueryUnderstandingStatus, RouteHint
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.core.config import Settings
from app.main import create_app
from app.structured import FilterOperator


class EmptyBackend:
    async def fetch_all(self, sql, parameters):
        return ()


def _ground(question: str):
    parsed = QueryParser().parse(
        request_id="prfd-sale-grounding",
        question_id="prfd-sale-grounding",
        question=question,
    )
    return OntologyGrounder().ground(parsed)


def _compile(question: str):
    grounded = _ground(question)
    assert grounded.route_hint is RouteHint.STRUCTURED
    assert grounded.understanding is not None
    assert grounded.understanding.status is QueryUnderstandingStatus.SUPPORTED
    assert grounded.structured_query is not None
    runtime = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=EmptyBackend(),
    ).state.runtime
    return grounded, runtime.structured_planner.compile(grounded.structured_query)


@pytest.mark.parametrize(
    "question",
    ("판매가능한 공모펀드", "현재 판매 중인 펀드"),
)
def test_general_sale_phrase_grounds_only_sale_yn_to_exact_active_literal(
    question: str,
) -> None:
    grounded, compiled = _compile(question)

    assert grounded.structured_query is not None
    assert grounded.structured_query.product_scope == "PRFD01N001"
    assert len(grounded.structured_query.filters) == 1
    condition = grounded.structured_query.filters[0]
    assert condition.field == "prfd.sale_available"
    assert condition.operator is FilterOperator.EQ
    assert condition.value == "판매중"
    selected = compiled.evidence_fields[0].field
    assert selected.source_column == "sale_yn"
    assert f'"{selected.physical_column}" = %s' in compiled.sql
    assert '"c007_thco_sale_yn"' not in compiled.sql
    assert '"c005_prvo_pbff_desc"' not in compiled.sql
    assert compiled.parameters == ("판매중",)


@pytest.mark.parametrize(
    "question",
    ("미래에셋에서 판매 가능한 펀드", "당사 판매 펀드"),
)
def test_company_sale_phrase_uses_only_thco_sale_yn(question: str) -> None:
    grounded, compiled = _compile(question)

    assert grounded.structured_query is not None
    condition = grounded.structured_query.filters[0]
    assert condition.field == "prfd.mirae_sale_available"
    assert condition.operator is FilterOperator.EQ
    assert condition.value == "Y"
    selected = compiled.evidence_fields[0].field
    assert selected.source_column == "thco_sale_yn"
    assert f'"{selected.physical_column}" = %s' in compiled.sql
    assert '"c006_sale_yn"' not in compiled.sql
    assert compiled.parameters == ("Y",)


@pytest.mark.parametrize("question", ("공모인 펀드", "사모 제외 펀드"))
def test_explicit_public_private_phrase_grounds_public_literal(question: str) -> None:
    grounded, compiled = _compile(question)

    assert grounded.structured_query is not None
    condition = grounded.structured_query.filters[0]
    assert condition.field == "prfd.public_private_category"
    assert condition.operator is FilterOperator.EQ
    assert condition.value == "공모"
    selected = compiled.evidence_fields[0].field
    assert selected.source_column == "prvo_pbff_desc"
    assert f'"{selected.physical_column}" = %s' in compiled.sql
    assert '"c006_sale_yn"' not in compiled.sql
    assert compiled.parameters == ("공모",)


def test_exact_completed_sale_literal_remains_available_only_when_requested() -> None:
    grounded, compiled = _compile("공모펀드 중 판매여부가 판매완료인 상품")

    assert grounded.structured_query is not None
    condition = grounded.structured_query.filters[0]
    assert condition.field == "prfd.sale_available"
    assert condition.value == "판매완료"
    assert compiled.parameters == ("판매완료",)


def test_general_prfd_query_has_no_global_sale_or_public_private_filter() -> None:
    grounded, compiled = _compile("공모펀드 중 상품코드가 ABC123인 상품")

    assert grounded.structured_query is not None
    assert grounded.structured_query.filters[0].field == "prfd.product_code"
    selected = compiled.evidence_fields[0].field
    assert selected.source_column == "itm_no"
    assert f'"{selected.physical_column}" = %s' in compiled.sql
    assert '"c006_sale_yn"' not in compiled.sql
    assert '"c007_thco_sale_yn"' not in compiled.sql
    assert '"c005_prvo_pbff_desc"' not in compiled.sql
    assert compiled.parameters == ("ABC123",)
