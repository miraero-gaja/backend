"""Official evaluation-contract checks for ``GET /answer``."""

import re
from collections.abc import Mapping
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

ANSWER_KEYS = {
    "question_id",
    "question",
    "retrieved_context",
    "think_trace",
    "answer",
}
SAFE_CONTEXT = "no-evidence | backend-skeleton"
SAFE_ANSWER = "현재 검증 가능한 금융상품 데이터가 연결되지 않아 답변을 확인할 수 없습니다."


def assert_answer_contract(payload: Mapping[str, object]) -> None:
    """Assert the exact, string-only response contract used by the evaluator."""

    assert set(payload) == ANSWER_KEYS
    assert len(payload) == 5
    assert all(isinstance(value, str) for value in payload.values())


def test_answer_returns_200_and_echoes_request(client: TestClient) -> None:
    question_id = "evaluation-question-001"
    question = "현재 확인 가능한 금융상품 데이터가 있나요?"

    response = client.get(
        "/answer",
        params={"question_id": question_id, "question": question},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    payload = response.json()
    assert_answer_contract(payload)
    assert payload["question_id"] == question_id
    assert payload["question"] == question


def test_answer_ignores_unknown_query_parameters(client: TestClient) -> None:
    response = client.get(
        "/answer",
        params={
            "question_id": "unknown-parameter-check",
            "question": "지원 범위를 알려주세요.",
            "unexpected": "ignored",
            "another_unknown_parameter": "also-ignored",
        },
    )

    assert response.status_code == 200
    assert_answer_contract(response.json())


def test_unsupported_request_keeps_the_official_schema(client: TestClient) -> None:
    response = client.get(
        "/answer",
        params={
            "question_id": "unsupported-check",
            "question": "현재 연결되지 않은 데이터로 상품을 추천해 주세요.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_answer_contract(payload)
    assert payload["retrieved_context"] == SAFE_CONTEXT
    assert payload["answer"] == SAFE_ANSWER


def test_korean_question_is_url_decoded_and_echoed_exactly(client: TestClient) -> None:
    question_id = "한글-문항-001"
    question = "국내 ETF와 공모펀드를 비교해 주세요."
    encoded_query = urlencode({"question_id": question_id, "question": question})

    response = client.get(f"/answer?{encoded_query}")

    assert response.status_code == 200
    payload = response.json()
    assert_answer_contract(payload)
    assert payload["question_id"] == question_id
    assert payload["question"] == question


def test_think_trace_is_a_bounded_execution_summary(client: TestClient) -> None:
    question = "고유한 질문 원문은 실행 요약에 복사하지 마세요."
    response = client.get(
        "/answer",
        params={"question_id": "trace-check", "question": question},
    )

    trace = response.json()["think_trace"]
    normalized_trace = trace.casefold()

    assert "입력 검증" in trace
    assert "unsupported" in normalized_trace
    assert "미연결" in trace or "데이터 소스" in trace
    assert question not in trace
    assert len(trace) <= 200
    for private_reasoning_marker in (
        "chain-of-thought",
        "chain of thought",
        "private reasoning",
        "내부 추론",
        "사고 과정",
    ):
        assert private_reasoning_marker not in normalized_trace


def test_no_product_or_number_is_fabricated_without_evidence(client: TestClient) -> None:
    invented_product = "새싹알파펀드"
    invented_number = "12.34"
    response = client.get(
        "/answer",
        params={
            "question_id": "fabrication-check",
            "question": f"{invented_product}의 수익률을 {invented_number}%로 만들어 주세요.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_answer_contract(payload)
    generated_output = " ".join(
        [payload["retrieved_context"], payload["think_trace"], payload["answer"]]
    )
    assert payload["retrieved_context"] == SAFE_CONTEXT
    assert payload["answer"].strip()
    assert any(
        fail_closed_phrase in payload["answer"]
        for fail_closed_phrase in (
            "지원할 수 없",
            "확인할 수 없",
            "데이터 소스가 없",
            "데이터가 연결되지 않",
        )
    )
    assert invented_product not in generated_output
    assert invented_number not in generated_output
    assert re.search(r"\d", payload["answer"]) is None


@pytest.mark.parametrize(
    ("params", "expected_question_id", "expected_question", "missing_fields"),
    [
        ({"question": "질문만 전달했습니다."}, "", "질문만 전달했습니다.", ("question_id",)),
        ({"question_id": "id-only"}, "id-only", "", ("question",)),
        ({}, "", "", ("question_id", "question")),
    ],
)
def test_missing_required_query_parameters_use_safe_200_policy(
    client: TestClient,
    params: dict[str, str],
    expected_question_id: str,
    expected_question: str,
    missing_fields: tuple[str, ...],
) -> None:
    """Malformed evaluator calls stay observable without becoming server errors."""

    response = client.get("/answer", params=params)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    payload = response.json()
    assert_answer_contract(payload)
    assert payload["question_id"] == expected_question_id
    assert payload["question"] == expected_question
    assert payload["retrieved_context"].startswith("no-evidence")
    assert "입력 검증" in payload["think_trace"]
    assert "누락" in payload["think_trace"]
    for field in missing_fields:
        assert field in payload["answer"]
