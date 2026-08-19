"""Failure-path checks for the evaluator-facing answer contract."""

from collections.abc import Mapping

from fastapi.testclient import TestClient

from app.api.routes import answer as answer_module
from app.main import app


def _raise_runtime_error(**_: str) -> None:
    raise RuntimeError("test-only internal detail")


def test_unexpected_runtime_failure_keeps_safe_answer_contract(
    monkeypatch,
) -> None:
    monkeypatch.setattr(answer_module.parser, "parse", _raise_runtime_error)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "failure-check",
                "question": "오류 응답을 확인합니다.",
            },
        )

    payload: Mapping[str, object] = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert set(payload) == {
        "question_id",
        "question",
        "retrieved_context",
        "think_trace",
        "answer",
    }
    assert all(isinstance(value, str) for value in payload.values())
    assert payload["question_id"] == "failure-check"
    assert payload["question"] == "오류 응답을 확인합니다."
    assert payload["retrieved_context"] == "no-evidence | backend-skeleton"
    assert "test-only internal detail" not in " ".join(payload.values())
