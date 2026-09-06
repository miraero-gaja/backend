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
from pathlib import Path
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
    GenerationValidationReason,
    GenerationValidationStatus,
    HyperClovaAnswerGenerator,
    PostGenerationValidation,
    PostGenerationValidator,
    build_evidence_only_prompt,
)
from app.llm import build_hcx_client
from app.main import create_app


LIVE_DATABASE_URL = os.getenv("DATABASE_URL")
LIVE_G2B_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "outputs"
    / "reports"
    / "g2b"
    / "g2b_structured_schema.json"
)
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


class RecordingPostGenerationValidator(PostGenerationValidator):
    def __init__(self) -> None:
        self.results: list[PostGenerationValidation] = []
        self.literal_evidence_candidate_counts: list[int] = []

    def validate(self, generation_input, prompt, raw_output):
        self.literal_evidence_candidate_counts.append(
            sum(
                placeholder.role in {"product_name", "product_identifier"}
                for placeholder in prompt.placeholders
            )
        )
        result = super().validate(generation_input, prompt, raw_output)
        self.results.append(result)
        return result


class StaticHCXTransport:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.output


class FailingHCXTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        raise RuntimeError("simulated HCX transport failure")


class RecordingBackend:
    def __init__(
        self,
        rows: Sequence[Mapping[str, Any]] = (),
        error: Exception | None = None,
    ) -> None:
        self.rows = tuple(rows)
        self.error = error
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any],
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append((sql, tuple(parameters)))
        if self.error is not None:
            raise self.error
        return self.rows


def _aum_rows() -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "__source_row_id": f"srid:v1:hcx-status-{index:03d}",
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


def _assert_public_schema(payload: dict[str, object]) -> None:
    assert set(payload) == ANSWER_FIELDS
    assert all(isinstance(value, str) for value in payload.values())


def _assert_generation_accepted(generator: RecordingAnswerGenerator) -> None:
    assert len(generator.inputs) == len(generator.results) == 1
    result = generator.results[0]
    assert result.provider == "hyperclova_x"
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.ACCEPTED


def _request(application, question_id: str) -> tuple[dict[str, object], dict[str, object]]:
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/answer",
            params={
                "question_id": question_id,
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_public_schema(payload)
    return payload, json.loads(payload["retrieved_context"])


def test_generation_entity_rejection_does_not_contaminate_supported_retrieval() -> None:
    backend = RecordingBackend(_aum_rows())
    transport = StaticHCXTransport(
        json.dumps(
            {"status": "SUPPORTED", "answer": "상품명[가짜 ETF]의 AUM입니다."},
            ensure_ascii=False,
        )
    )
    generator = RecordingAnswerGenerator(HyperClovaAnswerGenerator(transport))
    application = create_app(
        settings=Settings(_env_file=None),
        structured_backend=backend,
        answer_generator=generator,
    )

    payload, context = _request(application, "entity-rejection-status-isolation")

    assert context["status"] == "SUPPORTED"
    assert context["evidence_count"] == len(context["evidence"]) == 9
    assert len(backend.calls) == len(transport.calls) == 1
    result = generator.results[0]
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        result.validation_reason
        is GenerationValidationReason.ENTITY_MARKER_ROLE_MISMATCH
    )
    assert result.used_fallback is True
    assert payload["answer"] == generator.inputs[0].deterministic_fallback_answer


def test_structured_tool_exception_remains_tool_failure_with_hcx_fallback() -> None:
    backend = RecordingBackend(error=RuntimeError("simulated database failure"))
    transport = StaticHCXTransport(
        '{"status":"SUPPORTED","answer":"상품명[{{E001}}]입니다."}'
    )
    generator = RecordingAnswerGenerator(HyperClovaAnswerGenerator(transport))
    application = create_app(
        settings=Settings(_env_file=None),
        structured_backend=backend,
        answer_generator=generator,
    )

    payload, context = _request(application, "real-tool-failure-is-preserved")

    assert context == {
        "reason": "structured_retrieval_failed",
        "status": "TOOL_FAILURE",
    }
    assert len(backend.calls) == len(transport.calls) == 1
    assert generator.inputs[0].support_status is SupportStatus.UNSUPPORTED
    assert generator.results[0].used_fallback is True
    assert payload["answer"] == generator.inputs[0].deterministic_fallback_answer


def test_hcx_transport_failure_does_not_contaminate_supported_retrieval() -> None:
    backend = RecordingBackend(_aum_rows())
    transport = FailingHCXTransport()
    generator = RecordingAnswerGenerator(HyperClovaAnswerGenerator(transport))
    application = create_app(
        settings=Settings(_env_file=None),
        structured_backend=backend,
        answer_generator=generator,
    )

    payload, context = _request(application, "transport-failure-status-isolation")

    assert context["status"] == "SUPPORTED"
    assert context["evidence_count"] == len(context["evidence"]) == 9
    assert len(backend.calls) == len(transport.calls) == 1
    result = generator.results[0]
    assert result.validation_status is GenerationValidationStatus.TRANSPORT_ERROR
    assert (
        result.validation_reason
        is GenerationValidationReason.TRANSPORT_EXCEPTION
    )
    assert result.used_fallback is True
    assert payload["answer"] == generator.inputs[0].deterministic_fallback_answer


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
    generation_validator = RecordingPostGenerationValidator()
    generator = RecordingAnswerGenerator(
        HyperClovaAnswerGenerator(
            build_hcx_client(settings),
            validator=generation_validator,
        )
    )
    application = create_app(
        settings=settings,
        structured_schema_path=LIVE_G2B_SCHEMA_PATH,
        answer_generator=generator,
    )
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
    prompt = build_evidence_only_prompt(generator.inputs[0])
    allowed_entities = tuple(
        placeholder.value
        for placeholder in prompt.placeholders
        if placeholder.role in {"product_name", "product_identifier"}
    )
    normalized_spans = tuple(
        dict.fromkeys(
            span
            for validation in generation_validator.results
            for span in validation.normalized_entity_literals
        )
    )
    print(f"HCX_VALIDATOR_CLASS={type(generation_validator).__name__}")
    print(f"HCX_VALIDATOR_DELEGATE_CLASS={PostGenerationValidator.__name__}")
    for index, validation in enumerate(generation_validator.results, start=1):
        pass_name = "initial" if index == 1 else "repair"
        reason = validation.reason.value if validation.reason is not None else None
        candidates_count = generation_validator.literal_evidence_candidate_counts[
            index - 1
        ]
        print(
            f"HCX_VALIDATION_PASS={index}:{pass_name} "
            f"literal_evidence_candidates_count={candidates_count} "
            f"exact_matched_evidence_literals={validation.normalized_entity_literals!r} "
            f"normalized_entity_literals={validation.normalized_entity_literals!r} "
            f"residual_entity_literals={validation.residual_entity_literals!r} "
            f"reason={reason!r}"
        )
        print(
            "HCX_UNMARKED_PRODUCT_REFERENCE_SPANS="
            f"{validation.unmarked_product_reference_spans!r}"
        )
        print(
            "HCX_UNMARKED_PRODUCT_REFERENCE_NORMALIZED_SPANS="
            f"{validation.unmarked_product_reference_normalized_spans!r}"
        )
        print(
            "HCX_UNMARKED_PRODUCT_REFERENCE_RULE="
            f"{validation.unmarked_product_reference_rule!r}"
        )
        print(
            "HCX_UNMARKED_PRODUCT_REFERENCE_CLASSIFICATIONS="
            f"{validation.unmarked_product_reference_classifications!r}"
        )
        print(
            "HCX_UNMARKED_PRODUCT_REFERENCE_EVIDENCE_SOURCES="
            f"{validation.unmarked_product_reference_evidence_sources!r}"
        )
        print(f"HCX_NUMBER_SPANS={validation.detected_number_spans!r}")
        print(
            "HCX_NORMALIZED_NUMBER_SPANS="
            f"{validation.normalized_number_spans!r}"
        )
        print(
            "HCX_NUMBER_CLASSIFICATIONS="
            f"{validation.number_classifications!r}"
        )
        print(
            "HCX_ALLOWED_EVIDENCE_NUMBERS="
            f"{validation.allowed_evidence_numeric_values!r}"
        )
        print(
            "HCX_ALLOWED_DERIVED_NUMBERS="
            f"{validation.allowed_derived_numeric_values!r}"
        )
        print(f"HCX_NUMBER_RULE={validation.number_rule!r}")
        number_contexts = tuple(
            {
                "span": context.span,
                "start_index": context.start_index,
                "end_index": context.end_index,
                "context_repr": repr(context.structural_context),
                "line_index": context.line_index,
                "prefix_repr": repr(context.line_prefix),
                "line_length": context.line_length,
                "is_list_candidate": context.is_list_candidate,
                "candidate_rejection_reason": context.candidate_rejection_reason,
            }
            for context in validation.number_contexts
        )
        print(f"HCX_NUMBER_CONTEXTS={number_contexts!r}")
        print(
            "HCX_ENUMERATION_CANDIDATE_SEQUENCE="
            f"{validation.enumeration_candidate_sequence!r}"
        )
        marker_diagnostics = tuple(
            {
                "validation_pass_index": index,
                "validation_pass_name": pass_name,
                "mismatched_marker_token": mismatch.marker_token,
                "placeholder_id": mismatch.placeholder_id,
                "declared_role": mismatch.declared_role,
                "expected_role": mismatch.expected_role,
                "actual_role": mismatch.actual_role,
                "mapped_evidence_value": mismatch.mapped_evidence_value,
                "source_row_id": mismatch.source_row_id,
                "product_key": mismatch.product_key,
                "structural_context": mismatch.structural_context,
                "detection_rule": mismatch.detection_rule,
            }
            for mismatch in validation.marker_mismatches
        )
        print(f"HCX_ENTITY_MARKER_MISMATCHES={marker_diagnostics!r}")
        print(f"HCX_ENTITY_MARKER_RULE={validation.marker_rule!r}")
    print(f"HCX_ALLOWED_EVIDENCE_ENTITY_SET={allowed_entities!r}")
    assert set(normalized_spans) <= set(allowed_entities)
    _assert_generation_accepted(generator)
    assert payload["answer"] == generator.results[0].answer
    approved_aum_values = {
        str(item["normalized_value"])
        for item in evidence
        if item["source_field"] == "du_last_aum#1"
    }
    assert all(value in payload["answer"] for value in approved_aum_values)
    assert "{{NUM_" not in payload["answer"]

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
