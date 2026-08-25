"""Evidence-only generation and deterministic fallback checks."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.evidence.models import EvidenceItem, ReasonCode, SupportStatus
from app.generation import (
    DeterministicAnswerGenerator,
    GenerationInput,
    GenerationValidationStatus,
    HyperClovaAnswerGenerator,
    build_evidence_only_prompt,
)
from app.main import create_app


class StubTransport:
    def __init__(self, response: str = "", error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.response


class HangingTransport:
    async def generate(self, prompt: str) -> str:
        del prompt
        await asyncio.sleep(1)
        return "unreachable"


class StubBackend:
    def __init__(self, rows=()) -> None:
        self.rows = tuple(rows)

    async def fetch_all(self, sql, parameters):
        del sql, parameters
        return self.rows


def _evidence() -> tuple[EvidenceItem, ...]:
    common = {
        "product_key": "ETF001",
        "source_table": "PREF02N001",
        "source_row_id": "srid:v1:generation-001",
        "condition_id": None,
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
    fallback: str = "결정론적 fallback 답변입니다.",
) -> GenerationInput:
    return GenerationInput(
        question="해외 ETF 중 AUM이 큰 상품",
        support_status=status,
        reason_codes=(
            (ReasonCode.FIELD_NOT_AVAILABLE,)
            if status is SupportStatus.UNSUPPORTED
            else ()
        ),
        evidence=_evidence() if evidence is None else evidence,
        execution_trace="Structured 실행 성공 → Evidence 검증",
        deterministic_fallback_answer=fallback,
    )


def _json(status: SupportStatus, answer: str) -> str:
    return json.dumps(
        {"status": status.value, "answer": answer},
        ensure_ascii=False,
    )


def _generate(response: str, generation_input: GenerationInput | None = None):
    transport = StubTransport(response=response)
    result = asyncio.run(
        HyperClovaAnswerGenerator(transport).generate(generation_input or _input())
    )
    return transport, result


def test_evidence_only_hcx_stub_answer_is_accepted() -> None:
    transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품명[{{E002}}] (상품ID[{{E001}}])의 source-native 값은 {{E003}}입니다.",
        )
    )

    assert result.answer == (
        "상품명[검증 ETF] (상품ID[ETF001])의 source-native 값은 30입니다."
    )
    assert result.provider == "hyperclova_x"
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.ACCEPTED
    assert result.elapsed_ms >= 0
    assert len(transport.prompts) == 1


def test_prompt_contains_only_bounded_evidence_contract() -> None:
    prompt = build_evidence_only_prompt(_input()).text

    assert "제공된 evidence만 사용" in prompt
    assert '"source_field":"pd_nm#1"' in prompt
    assert '"value":"검증 ETF"' in prompt
    assert "raw_record" not in prompt
    assert "raw_value" not in prompt
    assert "profiling" not in prompt
    assert "투자 권유" in prompt


def test_unknown_product_name_uses_deterministic_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품명[가짜 ETF]의 값은 {{E003}}입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert result.answer == _input().deterministic_fallback_answer


def test_unknown_number_uses_deterministic_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품명[{{E002}}]의 값은 999입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_NUMBER


def test_unapproved_financial_unit_uses_deterministic_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품명[{{E002}}]의 값은 {{E003}}억입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_UNIT


def test_empty_hcx_response_uses_deterministic_fallback() -> None:
    _transport, result = _generate("")

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_EMPTY


def test_timeout_or_transport_exception_uses_deterministic_fallback() -> None:
    for error in (TimeoutError("test timeout"), RuntimeError("transport failed")):
        transport = StubTransport(error=error)
        result = asyncio.run(HyperClovaAnswerGenerator(transport).generate(_input()))

        assert result.answer == _input().deterministic_fallback_answer
        assert result.used_fallback is True
        assert (
            result.validation_status
            is GenerationValidationStatus.TRANSPORT_ERROR
        )

    timed_out = asyncio.run(
        HyperClovaAnswerGenerator(
            HangingTransport(),
            timeout_seconds=0.001,
        ).generate(_input())
    )
    assert timed_out.used_fallback is True
    assert timed_out.validation_status is GenerationValidationStatus.TRANSPORT_ERROR


def test_unmarked_unknown_product_reference_uses_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "가짜 ETF는 검증된 결과입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY


def test_unsupported_qualitative_financial_claim_uses_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품명[{{E002}}]은 수익률 전망이 좋습니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY


def test_status_change_uses_deterministic_fallback() -> None:
    _transport, result = _generate(
        _json(SupportStatus.UNSUPPORTED, "현재 확인할 수 없습니다.")
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_STATUS


def test_unsupported_recommendation_uses_deterministic_fallback() -> None:
    generation_input = _input(
        status=SupportStatus.UNSUPPORTED,
        evidence=(),
        fallback="현재 승인된 근거로 확인할 수 없습니다.",
    )
    _transport, result = _generate(
        _json(SupportStatus.UNSUPPORTED, "가짜 ETF를 추천합니다."),
        generation_input,
    )

    assert result.answer == generation_input.deterministic_fallback_answer
    assert result.used_fallback is True
    assert (
        result.validation_status
        is GenerationValidationStatus.REJECTED_RECOMMENDATION
    )


def test_deterministic_generator_returns_existing_answer_unchanged() -> None:
    generation_input = _input(fallback="기존 deterministic 답변")
    result = asyncio.run(
        DeterministicAnswerGenerator().generate(generation_input)
    )

    assert result.answer == "기존 deterministic 답변"
    assert result.provider == "deterministic"
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.DETERMINISTIC


def _aum_row():
    return {
        "__source_row_id": "srid:v1:generation-api",
        "__logical_table_id": "PREF02N001",
        "__raw_record": {
            "pd_itm_no#1": {"type": "STRING", "value": "ETF001"},
            "pd_nm#1": {"type": "STRING", "value": "검증 ETF"},
            "du_last_aum#1": {"type": "DECIMAL", "value": "30"},
        },
        "__parse_statuses": {
            "pd_itm_no#1": "OK",
            "pd_nm#1": "OK",
            "du_last_aum#1": "OK",
        },
        "__value_000": "ETF001",
        "__value_001": "검증 ETF",
        "__value_002": Decimal("30"),
    }


def test_answer_wiring_accepts_safe_generation_and_keeps_five_strings() -> None:
    transport = StubTransport(
        response=_json(
            SupportStatus.SUPPORTED,
            "상품명[{{E002}}] (상품ID[{{E001}}])의 값은 {{E003}}입니다.",
        )
    )
    application = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=StubBackend((_aum_row(),)),
        answer_generator=HyperClovaAnswerGenerator(transport),
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "generation-api",
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
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
    assert payload["answer"] == (
        "상품명[검증 ETF] (상품ID[ETF001])의 값은 30입니다."
    )


def test_answer_transport_failure_matches_deterministic_response() -> None:
    settings = Settings(_env_file=None, database_url=None)
    parameters = {
        "question_id": "generation-fallback",
        "question": "해외 ETF 중 AUM이 큰 상품 3개",
    }
    deterministic_app = create_app(
        settings=settings,
        structured_backend=StubBackend((_aum_row(),)),
    )
    fallback_app = create_app(
        settings=settings,
        structured_backend=StubBackend((_aum_row(),)),
        answer_generator=HyperClovaAnswerGenerator(
            StubTransport(error=TimeoutError("test timeout"))
        ),
    )

    with TestClient(deterministic_app) as deterministic_client:
        expected = deterministic_client.get("/answer", params=parameters).json()
    with TestClient(fallback_app) as fallback_client:
        actual = fallback_client.get("/answer", params=parameters).json()

    assert actual == expected
