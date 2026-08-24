"""Core end-to-end checks for the evaluator-facing GET /answer contract."""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.answer_renderer import MAX_THINK_TRACE_CHARS
from app.core.config import Settings
from app.evidence.serializer import MAX_RETRIEVED_CONTEXT_CHARS
from app.main import create_app


ANSWER_FIELDS = {
    "question_id",
    "question",
    "retrieved_context",
    "think_trace",
    "answer",
}


class StubBackend:
    def __init__(self, rows=(), error: Exception | None = None) -> None:
        self.rows = tuple(rows)
        self.error = error
        self.calls = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        if self.error is not None:
            raise self.error
        return self.rows


def _aum_rows():
    return tuple(
        {
            "__source_row_id": f"srid:v1:answer-{index:03d}",
            "__logical_table_id": "PREF02N001",
            "__raw_record": {
                "pd_itm_no#1": {"type": "STRING", "value": f"ETF{index:03d}"},
                "pd_nm#1": {"type": "STRING", "value": f"해외 ETF {index}"},
                "du_last_aum#1": {"type": "DECIMAL", "value": value},
            },
            "__parse_statuses": {
                "pd_itm_no#1": "OK",
                "pd_nm#1": "OK",
                "du_last_aum#1": "OK",
            },
            "__value_000": f"ETF{index:03d}",
            "__value_001": f"해외 ETF {index}",
            "__value_002": Decimal(value),
        }
        for index, value in enumerate(("30", "20", "10"), start=1)
    )


def _client(backend: StubBackend) -> TestClient:
    application = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    )
    return TestClient(application, raise_server_exceptions=False)


def _assert_contract(payload) -> None:
    assert set(payload) == ANSWER_FIELDS
    assert all(isinstance(value, str) for value in payload.values())
    assert len(payload["think_trace"]) <= MAX_THINK_TRACE_CHARS
    assert len(payload["retrieved_context"]) <= MAX_RETRIEVED_CONTEXT_CHARS


def test_answer_supported_aum_top_three_core_e2e() -> None:
    backend = StubBackend(_aum_rows())
    question_id = "q1"
    question = "해외 ETF 중 AUM이 큰 상품 3개"

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={"question_id": question_id, "question": question},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    payload = response.json()
    _assert_contract(payload)
    assert payload["question_id"] == question_id
    assert payload["question"] == question
    context = json.loads(payload["retrieved_context"])
    assert context["status"] == "SUPPORTED"
    assert context["evidence_count"] == 9
    assert {item["source_field"] for item in context["evidence"]} == {
        "pd_itm_no#1",
        "pd_nm#1",
        "du_last_aum#1",
    }
    assert {item["product_key"] for item in context["evidence"]} == {
        "ETF001",
        "ETF002",
        "ETF003",
    }
    assert "SUPPORTED" in payload["think_trace"]
    assert "SORT_DESC" in payload["think_trace"]
    assert question not in payload["think_trace"]
    assert "3건" in payload["answer"]
    assert "해외 ETF 1 (ETF001) | AUM source-native 값: 30" in payload["answer"]
    assert len(backend.calls) == 1


def test_answer_closed_expense_ratio_is_unsupported_without_backend() -> None:
    backend = StubBackend(_aum_rows())

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "expense-closed",
                "question": "해외 ETF 총보수 0.5% 이하",
            },
        )

    payload = response.json()
    _assert_contract(payload)
    assert response.status_code == 200
    assert backend.calls == []
    assert json.loads(payload["retrieved_context"]) == {
        "reason": "unit_conversion_not_approved",
        "status": "UNSUPPORTED",
    }
    assert "UNSUPPORTED" in payload["think_trace"]
    assert "단위" in payload["answer"]


def test_answer_supported_query_zero_rows_is_no_match() -> None:
    backend = StubBackend()

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "no-match",
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
            },
        )

    payload = response.json()
    _assert_contract(payload)
    assert response.status_code == 200
    assert json.loads(payload["retrieved_context"])["status"] == "NO_MATCH"
    assert "NO_MATCH" in payload["think_trace"]
    assert "조건에 맞는 상품" in payload["answer"]
    assert len(backend.calls) == 1


def test_answer_backend_exception_is_tool_failure_with_http_200() -> None:
    backend = StubBackend(error=RuntimeError("database unavailable"))

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "tool-failure",
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
            },
        )

    payload = response.json()
    _assert_contract(payload)
    assert response.status_code == 200
    assert json.loads(payload["retrieved_context"])["status"] == "TOOL_FAILURE"
    assert "TOOL_FAILURE" in payload["think_trace"]
    assert "시스템 조회 실패" in payload["answer"]
    assert len(backend.calls) == 1


def test_answer_unknown_field_fails_closed() -> None:
    backend = StubBackend(_aum_rows())

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "unknown-field",
                "question": "해외 ETF 변동성 높은 순 3개",
            },
        )

    payload = response.json()
    _assert_contract(payload)
    assert response.status_code == 200
    context = json.loads(payload["retrieved_context"])
    assert context == {
        "reason": "semantic_field_not_recognized",
        "status": "UNSUPPORTED",
    }
    assert backend.calls == []
    assert "승인된 structured field" in payload["answer"]


def test_answer_ignores_extra_query_parameter() -> None:
    backend = StubBackend(_aum_rows())

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "extra-param",
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
                "undefined_parameter": "ignored",
            },
        )

    assert response.status_code == 200
    _assert_contract(response.json())


@pytest.mark.parametrize(
    ("question_id", "question"),
    (
        ("normal-id", "지원 범위를 알려주세요."),
        ("", ""),
        ("한글-문항-😀", "해외 ETF 중 AUM이 큰 상품 3개"),
    ),
)
def test_answer_echoes_query_params_exactly_and_all_values_are_strings(
    question_id: str,
    question: str,
) -> None:
    backend = StubBackend()

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={"question_id": question_id, "question": question},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload)
    assert payload["question_id"] == question_id
    assert payload["question"] == question
