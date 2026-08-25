"""Authenticated HCX HTTP transport and composition safety checks."""

from __future__ import annotations

import asyncio
import json
import secrets
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.evidence.models import EvidenceItem, ReasonCode, SupportStatus
from app.generation import (
    DeterministicAnswerGenerator,
    GenerationInput,
    GenerationValidationStatus,
    HyperClovaAnswerGenerator,
)
from app.llm import HCXTransportError, NaverCloudHCXClient
from app.main import create_app


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def close(self) -> None:
        return None


class FakeOpenUrl:
    def __init__(self, response: FakeResponse | None = None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class EmptyBackend:
    async def fetch_all(self, sql, parameters):
        del sql, parameters
        return ()


class StatusEchoTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        status = next(
            line.removeprefix("status=")
            for line in prompt.splitlines()
            if line.startswith("status=")
        )
        return json.dumps(
            {
                "status": status,
                "answer": "현재 승인된 근거로 확인할 수 없습니다.",
            },
            ensure_ascii=False,
        )


def _secret() -> str:
    return secrets.token_urlsafe(32)


def _api_body(content: str) -> bytes:
    return json.dumps(
        {
            "status": {"code": "20000", "message": "OK"},
            "result": {
                "message": {"role": "assistant", "content": content},
                "finishReason": "stop",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _evidence() -> tuple[EvidenceItem, ...]:
    common = {
        "product_key": "ETF001",
        "source_table": "PREF02N001",
        "source_row_id": "srid:v1:hcx-http",
        "decision": SupportStatus.SUPPORTED,
    }
    return (
        EvidenceItem(
            **common,
            source_field="pd_itm_no#1",
            raw_value="ETF001",
            normalized_value="ETF001",
        ),
        EvidenceItem(
            **common,
            source_field="pd_nm#1",
            raw_value="검증 ETF",
            normalized_value="검증 ETF",
        ),
        EvidenceItem(
            **common,
            source_field="du_last_aum#1",
            raw_value="30",
            normalized_value="30",
        ),
    )


def _input(
    *,
    status: SupportStatus = SupportStatus.SUPPORTED,
    evidence: tuple[EvidenceItem, ...] | None = None,
) -> GenerationInput:
    return GenerationInput(
        question="해외 ETF 중 AUM이 큰 상품",
        support_status=status,
        reason_codes=(
            (ReasonCode.NO_MATCH,)
            if status is SupportStatus.NO_MATCH
            else (
                (ReasonCode.FIELD_NOT_AVAILABLE,)
                if status is SupportStatus.UNSUPPORTED
                else ()
            )
        ),
        evidence=_evidence() if evidence is None else evidence,
        execution_trace="Structured 실행 → Evidence 검증",
        deterministic_fallback_answer="검증된 deterministic fallback",
    )


def _client(opener: FakeOpenUrl, key: str | None = None) -> NaverCloudHCXClient:
    return NaverCloudHCXClient(
        api_url="https://clovastudio.invalid/v3/chat-completions/HCX-005",
        api_key=SecretStr(key or _secret()),
        open_url=opener,
    )


def _generator_result(opener: FakeOpenUrl, generation_input=None):
    return asyncio.run(
        HyperClovaAnswerGenerator(_client(opener)).generate(
            generation_input or _input()
        )
    )


def test_hcx_disabled_never_builds_transport(monkeypatch) -> None:
    def unexpected_transport(_settings):
        raise AssertionError("transport must remain disabled")

    monkeypatch.setattr("app.composition.build_hcx_client", unexpected_transport)
    application = create_app(
        settings=Settings(
            _env_file=None,
            hcx_enabled=False,
            hcx_api_key=_secret(),
            hcx_api_url="https://clovastudio.invalid/v3/chat-completions/HCX-005",
            database_url=None,
        ),
        structured_backend=EmptyBackend(),
    )

    assert isinstance(
        application.state.runtime.answer_generator,
        DeterministicAnswerGenerator,
    )


def test_hcx_enabled_with_missing_config_starts_deterministically() -> None:
    application = create_app(
        settings=Settings(
            _env_file=None,
            hcx_enabled=True,
            hcx_api_key=None,
            hcx_api_url=None,
            database_url=None,
        ),
        structured_backend=EmptyBackend(),
    )

    assert isinstance(
        application.state.runtime.answer_generator,
        DeterministicAnswerGenerator,
    )


def test_valid_hcx_config_wires_generation_without_changing_answer_schema(
    monkeypatch,
) -> None:
    transport = StatusEchoTransport()
    monkeypatch.setattr(
        "app.composition.build_hcx_client",
        lambda _settings: transport,
    )
    application = create_app(
        settings=Settings(
            _env_file=None,
            hcx_enabled=True,
            hcx_api_key=_secret(),
            hcx_api_url="https://clovastudio.invalid/v3/chat-completions/HCX-005",
            database_url=None,
        ),
        structured_backend=EmptyBackend(),
    )

    assert isinstance(
        application.state.runtime.answer_generator,
        HyperClovaAnswerGenerator,
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "hcx-wiring",
                "question": "해외 ETF 변동성 높은 순 3개",
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert set(payload) == {
        "question_id",
        "question",
        "retrieved_context",
        "think_trace",
        "answer",
    }
    assert all(isinstance(value, str) for value in payload.values())
    assert transport.calls == 1


def test_valid_hcx_http_response_reaches_post_validator() -> None:
    candidate = json.dumps(
        {
            "status": "SUPPORTED",
            "answer": "상품명[{{E002}}]의 값은 {{E003}}입니다.",
        },
        ensure_ascii=False,
    )
    opener = FakeOpenUrl(FakeResponse(_api_body(candidate)))

    result = _generator_result(opener)

    assert result.answer == "상품명[검증 ETF]의 값은 30입니다."
    assert result.provider == "hyperclova_x"
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.ACCEPTED
    request, timeout = opener.calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    headers = {name.lower(): value for name, value in request.header_items()}
    assert timeout == 4.0
    assert request.method == "POST"
    assert headers["authorization"].startswith("Bearer ")
    assert headers["x-ncp-clovastudio-request-id"]
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["accept"] == "application/json"
    assert payload["messages"][0]["content"].startswith("[SYSTEM]\n")
    assert "raw_record" not in payload["messages"][0]["content"]
    assert "profiling" not in payload["messages"][0]["content"]
    assert set(payload) == {
        "messages",
        "topP",
        "topK",
        "maxTokens",
        "temperature",
        "repetitionPenalty",
        "stop",
        "includeAiFilters",
    }
    assert payload["maxTokens"] == 256


@pytest.mark.parametrize("status", (401, 403, 429, 500))
def test_hcx_http_errors_use_fallback(status: int) -> None:
    error = HTTPError(
        "https://clovastudio.invalid/redacted",
        status,
        "request failed",
        hdrs=None,
        fp=None,
    )
    result = _generator_result(FakeOpenUrl(error=error))

    assert result.answer == _input().deterministic_fallback_answer
    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.TRANSPORT_ERROR


@pytest.mark.parametrize(
    "error",
    (TimeoutError("timeout"), URLError("connection refused")),
)
def test_timeout_or_connection_error_uses_fallback(error) -> None:
    result = _generator_result(FakeOpenUrl(error=error))

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.TRANSPORT_ERROR


@pytest.mark.parametrize(
    "body",
    (
        b"not-json",
        b"{}",
        b'{"result":{"message":{"content":""}}}',
    ),
)
def test_malformed_or_empty_hcx_response_uses_fallback(body: bytes) -> None:
    result = _generator_result(FakeOpenUrl(FakeResponse(body)))

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.TRANSPORT_ERROR


def test_hcx_candidate_outside_evidence_is_rejected_after_http() -> None:
    candidate = json.dumps(
        {
            "status": "SUPPORTED",
            "answer": "상품명[가짜 ETF]의 값은 999억입니다.",
        },
        ensure_ascii=False,
    )
    result = _generator_result(
        FakeOpenUrl(FakeResponse(_api_body(candidate)))
    )

    assert result.used_fallback is True
    assert result.validation_status in {
        GenerationValidationStatus.REJECTED_ENTITY,
        GenerationValidationStatus.REJECTED_NUMBER,
        GenerationValidationStatus.REJECTED_UNIT,
    }


def test_api_key_never_appears_in_repr_or_transport_error() -> None:
    key = _secret()
    response_body = json.dumps({"debug": key}).encode("utf-8")
    error = HTTPError(
        "https://clovastudio.invalid/redacted",
        401,
        "unauthorized",
        hdrs=None,
        fp=FakeResponse(response_body),
    )
    client = _client(FakeOpenUrl(error=error), key=key)

    with pytest.raises(HCXTransportError) as captured:
        asyncio.run(client.generate("safe prompt"))

    combined = f"{client!r}\n{captured.value}"
    assert key not in combined
    assert response_body.decode("utf-8") not in combined
    assert str(captured.value) == "hcx_http_error status=401"


@pytest.mark.parametrize(
    "status",
    (SupportStatus.UNSUPPORTED, SupportStatus.NO_MATCH),
)
def test_hcx_cannot_change_unsupported_or_no_match_status(status) -> None:
    candidate = json.dumps(
        {"status": "SUPPORTED", "answer": "상품명[{{E001}}]을 추천합니다."},
        ensure_ascii=False,
    )
    generation_input = _input(status=status, evidence=())
    result = _generator_result(
        FakeOpenUrl(FakeResponse(_api_body(candidate))),
        generation_input,
    )

    assert result.answer == generation_input.deterministic_fallback_answer
    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_STATUS


def test_invalid_hcx_url_does_not_fail_application_startup(capsys) -> None:
    key = _secret()
    application = create_app(
        settings=Settings(
            _env_file=None,
            hcx_enabled=True,
            hcx_api_key=key,
            hcx_api_url="http://not-https.invalid/v3/chat-completions/HCX-005",
            database_url=None,
        ),
        structured_backend=EmptyBackend(),
    )

    captured = capsys.readouterr()
    assert isinstance(
        application.state.runtime.answer_generator,
        DeterministicAnswerGenerator,
    )
    assert key not in captured.out
    assert key not in captured.err
