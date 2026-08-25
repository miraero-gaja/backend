"""Opt-in full PostgreSQL + HyperCLOVA X ``/answer`` validation.

The live test is read-only and requires the application staging ``DATABASE_URL``
plus all three HCX settings.  The two state-preservation tests use local stubs,
so they add no external calls or model cost.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.answer_renderer import MAX_THINK_TRACE_CHARS
from app.core.config import Settings
from app.evidence.models import SupportStatus
from app.generation import (
    AnswerGenerator,
    GenerationInput,
    GenerationResult,
    GenerationValidationStatus,
    HyperClovaAnswerGenerator,
)
from app.llm import build_hcx_client
from app.main import create_app


LIVE_DATABASE_URL = os.getenv("DATABASE_URL")
HCX_ENABLED = os.getenv("HCX_ENABLED", "").lower() in {"1", "true", "yes"}
HCX_API_KEY = os.getenv("HCX_API_KEY")
HCX_API_URL = os.getenv("HCX_API_URL")
LIVE_E2E_READY = bool(
    LIVE_DATABASE_URL and HCX_ENABLED and HCX_API_KEY and HCX_API_URL
)
ANSWER_FIELDS = {
    "question_id",
    "question",
    "retrieved_context",
    "think_trace",
    "answer",
}
_UNAPPROVED_ABSOLUTE_UNIT = re.compile(r"억원|백만원|만원|천원|(?<![가-힣])원(?![가-힣])|%")


class RecordingAnswerGenerator:
    def __init__(self, delegate: AnswerGenerator) -> None:
        self.delegate = delegate
        self.inputs: list[GenerationInput] = []
        self.results: list[GenerationResult] = []

    async def generate(self, generation_input: GenerationInput) -> GenerationResult:
        self.inputs.append(generation_input)
        result = await self.delegate.generate(generation_input)
        self.results.append(result)
        return result


class StaticHCXTransport:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.output


class RecordingBackend:
    def __init__(self, rows: Sequence[Mapping[str, Any]] = ()) -> None:
        self.rows = tuple(rows)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any],
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append((sql, tuple(parameters)))
        return self.rows


def _assert_public_schema(payload: dict[str, object]) -> None:
    assert set(payload) == ANSWER_FIELDS
    assert all(isinstance(value, str) for value in payload.values())


def _assert_generation_finished_safely(generator: RecordingAnswerGenerator) -> None:
    assert len(generator.inputs) == len(generator.results) == 1
    generation_input = generator.inputs[0]
    result = generator.results[0]
    assert result.provider == "hyperclova_x"
    if result.used_fallback:
        assert result.answer == generation_input.deterministic_fallback_answer
        assert result.validation_status is not GenerationValidationStatus.ACCEPTED
    else:
        assert result.validation_status is GenerationValidationStatus.ACCEPTED


@pytest.mark.skipif(
    not LIVE_E2E_READY,
    reason=(
        "DATABASE_URL and HCX_ENABLED/HCX_API_KEY/HCX_API_URL are required "
        "for the full live E2E"
    ),
)
def test_live_pref02_postgres_hcx_answer_e2e() -> None:
    """Use one real HCX request after real read-only staging retrieval."""

    settings = Settings(
        _env_file=None,
        database_url=LIVE_DATABASE_URL,
        hcx_enabled=True,
        hcx_api_key=HCX_API_KEY,
        hcx_api_url=HCX_API_URL,
    )
    generator = RecordingAnswerGenerator(
        HyperClovaAnswerGenerator(build_hcx_client(settings))
    )
    application = create_app(settings=settings, answer_generator=generator)
    question_id = "pref02-hcx-live-e2e"
    question = "해외 ETF 중 AUM이 큰 상품 3개"

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/answer",
            params={"question_id": question_id, "question": question},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_public_schema(payload)
    assert payload["question_id"] == question_id
    assert payload["question"] == question
    assert payload["answer"]
    assert 0 < len(payload["think_trace"]) <= MAX_THINK_TRACE_CHARS

    context = json.loads(payload["retrieved_context"])
    assert context["status"] == "SUPPORTED"
    assert context["truncated"] is False
    evidence = context["evidence"]
    assert context["evidence_count"] == len(evidence) == 9
    assert {item["source_table"] for item in evidence} == {"PREF02N001"}
    assert {item["source_field"] for item in evidence} == {
        "pd_itm_no#1",
        "pd_nm#1",
        "du_last_aum#1",
    }

    rows: dict[str, dict[str, dict[str, object]]] = {}
    for item in evidence:
        assert item["source_row_id"]
        rows.setdefault(item["source_row_id"], {})[item["source_field"]] = item
    assert len(rows) == 3
    aum_values: list[Decimal] = []
    for row in rows.values():
        identifier = row["pd_itm_no#1"]["normalized_value"]
        name = row["pd_nm#1"]["normalized_value"]
        metric = row["du_last_aum#1"]
        assert isinstance(identifier, str) and identifier
        assert isinstance(name, str) and name
        assert {item["product_key"] for item in row.values()} == {identifier}
        assert "unit" not in metric
        aum_values.append(Decimal(metric["normalized_value"]))
    assert aum_values == sorted(aum_values, reverse=True)

    assert generator.inputs[0].support_status is SupportStatus.SUPPORTED
    assert len(generator.inputs[0].evidence) == 9
    _assert_generation_finished_safely(generator)
    assert payload["answer"] == generator.results[0].answer

    # Remove every validated source value before looking for an invented AUM
    # unit.  A unit-like token inside an approved product name remains evidence.
    answer_without_evidence = payload["answer"]
    source_values = {
        str(item["normalized_value"])
        for item in evidence
        if item["normalized_value"] is not None
    }
    for value in sorted(source_values, key=len, reverse=True):
        answer_without_evidence = answer_without_evidence.replace(value, "")
    assert _UNAPPROVED_ABSOLUTE_UNIT.search(answer_without_evidence) is None


def test_expense_ratio_remains_unsupported_before_backend_and_generation_status() -> None:
    backend = RecordingBackend()
    transport = StaticHCXTransport(
        '{"status":"SUPPORTED","answer":"가짜 상품을 추천합니다."}'
    )
    generator = RecordingAnswerGenerator(HyperClovaAnswerGenerator(transport))
    application = create_app(
        settings=Settings(_env_file=None),
        structured_backend=backend,
        answer_generator=generator,
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "pref02-expense-unsupported",
                "question": "해외 ETF 총보수 0.5% 이하",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_public_schema(payload)
    assert json.loads(payload["retrieved_context"])["status"] == "UNSUPPORTED"
    assert backend.calls == []
    assert len(transport.calls) == 1
    assert generator.inputs[0].support_status is SupportStatus.UNSUPPORTED
    assert generator.results[0].used_fallback is True
    assert (
        generator.results[0].validation_status
        is GenerationValidationStatus.REJECTED_STATUS
    )
    assert payload["answer"] == generator.inputs[0].deterministic_fallback_answer


def test_supported_zero_rows_remains_no_match_after_generation() -> None:
    backend = RecordingBackend()
    transport = StaticHCXTransport(
        '{"status":"SUPPORTED","answer":"가짜 상품을 추천합니다."}'
    )
    generator = RecordingAnswerGenerator(HyperClovaAnswerGenerator(transport))
    application = create_app(
        settings=Settings(_env_file=None),
        structured_backend=backend,
        answer_generator=generator,
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": "pref02-zero-rows",
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_public_schema(payload)
    assert json.loads(payload["retrieved_context"])["status"] == "NO_MATCH"
    assert len(backend.calls) == 1
    assert len(transport.calls) == 1
    assert generator.inputs[0].support_status is SupportStatus.NO_MATCH
    assert generator.results[0].used_fallback is True
    assert (
        generator.results[0].validation_status
        is GenerationValidationStatus.REJECTED_STATUS
    )
    assert payload["answer"] == generator.inputs[0].deterministic_fallback_answer
