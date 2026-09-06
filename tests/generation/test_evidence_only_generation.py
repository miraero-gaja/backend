"""Evidence-only generation and deterministic fallback checks."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.evidence.models import EvidenceItem, ReasonCode, SupportStatus
from app.generation import (
    DeterministicAnswerGenerator,
    GenerationInput,
    GenerationValidationReason,
    GenerationValidationStatus,
    HyperClovaAnswerGenerator,
    PostGenerationValidator,
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


class SequenceTransport:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected extra generation attempt")
        return self.responses.pop(0)


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


def _three_product_evidence() -> tuple[EvidenceItem, ...]:
    items: list[EvidenceItem] = []
    for index, value in enumerate(("30", "20", "10"), start=1):
        common = {
            "product_key": f"ETF{index:03d}",
            "source_table": "PREF02N001",
            "source_row_id": f"srid:v1:generation-{index:03d}",
            "condition_id": None,
            "decision": SupportStatus.SUPPORTED,
        }
        items.extend(
            (
                EvidenceItem(
                    **common,
                    source_field="pd_itm_no#1",
                    raw_value=f"ETF{index:03d}",
                    normalized_value=f"ETF{index:03d}",
                ),
                EvidenceItem(
                    **common,
                    source_field="pd_nm#1",
                    raw_value=f"검증 해외 ETF {index}",
                    normalized_value=f"검증 해외 ETF {index}",
                ),
                EvidenceItem(
                    **common,
                    source_field="du_last_aum#1",
                    raw_value=value,
                    normalized_value=value,
                ),
            )
        )
    return tuple(items)


def _live_named_product_evidence() -> tuple[EvidenceItem, ...]:
    products = (
        ("VOO", "Vanguard 500 Index Fund;ETF", "997351790000"),
        ("IVV", "iShares Core S&P 500 ETF", "889429740000"),
        ("SPY", "State Street SPDR S&P 500 ETF Trust", "820108800000"),
    )
    items: list[EvidenceItem] = []
    for index, (identifier, name, value) in enumerate(products, start=1):
        common = {
            "product_key": identifier,
            "source_table": "PREF02N001",
            "source_row_id": f"srid:v1:live-named-{index:03d}",
            "condition_id": None,
            "decision": SupportStatus.SUPPORTED,
        }
        items.extend(
            (
                EvidenceItem(
                    **common,
                    source_field="pd_itm_no#1",
                    raw_value=identifier,
                    normalized_value=identifier,
                ),
                EvidenceItem(
                    **common,
                    source_field="pd_nm#1",
                    raw_value=name,
                    normalized_value=name,
                ),
                EvidenceItem(
                    **common,
                    source_field="du_last_aum#1",
                    raw_value=value,
                    normalized_value=value,
                ),
            )
        )
    return tuple(items)


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
            "상품명[{{E002}}] (상품ID[{{E001}}])의 source-native 값은 {{NUM_001}}입니다.",
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
    assert "{{NUM_" not in result.answer


def test_exact_evidence_product_name_literal_is_deterministically_grounded() -> None:
    generation_input = _input()
    prompt = build_evidence_only_prompt(generation_input)
    raw_output = _json(
        SupportStatus.SUPPORTED,
        "검증 ETF의 값은 {{NUM_001}}입니다.",
    )

    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        raw_output,
    )

    assert validation.accepted is True
    assert validation.answer == "검증 ETF의 값은 30입니다."
    assert validation.reason is GenerationValidationReason.EVIDENCE_LITERAL_NORMALIZED
    assert validation.normalized_entity_literals == ("검증 ETF",)


def test_exact_evidence_identifier_literal_is_deterministically_grounded() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품ID ETF001의 값은 {{NUM_001}}입니다.",
        )
    )

    assert result.answer == "상품ID ETF001의 값은 30입니다."
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.ACCEPTED
    assert (
        result.validation_reason
        is GenerationValidationReason.EVIDENCE_LITERAL_NORMALIZED
    )


def test_exact_name_and_identifier_literals_are_both_grounded() -> None:
    generation_input = _input()
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "**검증 ETF** (ETF001)의 값은 {{NUM_001}}입니다.",
        ),
    )

    assert validation.accepted is True
    assert validation.answer == "**검증 ETF** (ETF001)의 값은 30입니다."
    assert validation.normalized_entity_literals == ("검증 ETF", "ETF001")


def test_three_products_exact_names_and_identifiers_are_all_grounded() -> None:
    generation_input = _input(evidence=_three_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            (
                "**검증 해외 ETF 1** (ETF001): {{NUM_001}}; "
                "`검증 해외 ETF 2` (ETF002): {{NUM_002}}; "
                "검증 해외 ETF 3 (ETF003): {{NUM_003}}"
            ),
        ),
    )

    assert validation.accepted is True
    assert validation.answer == (
        "**검증 해외 ETF 1** (ETF001): 30; "
        "`검증 해외 ETF 2` (ETF002): 20; "
        "검증 해외 ETF 3 (ETF003): 10"
    )
    assert validation.normalized_entity_literals == (
        "검증 해외 ETF 1",
        "ETF001",
        "검증 해외 ETF 2",
        "ETF002",
        "검증 해외 ETF 3",
        "ETF003",
    )


def test_live_product_entities_generic_etf_and_derived_index_are_accepted() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            (
                "Vanguard 500 Index Fund;ETF (VOO): {{NUM_001}}; "
                "iShares Core S&P 500 ETF (IVV): {{NUM_002}}; "
                "State Street SPDR S&P 500 ETF Trust (SPY): {{NUM_003}}. "
                "세 상품은 모두 해외 ETF이며 S&P 500 관련 상품입니다."
            ),
        ),
    )

    assert validation.accepted is True
    assert validation.normalized_entity_literals == (
        "Vanguard 500 Index Fund;ETF",
        "VOO",
        "iShares Core S&P 500 ETF",
        "IVV",
        "State Street SPDR S&P 500 ETF Trust",
        "SPY",
    )
    assert validation.unmarked_product_reference_normalized_spans == (
        "세 상품은 모두 해외 ETF",
    )
    assert validation.unmarked_product_reference_classifications == (
        "GENERIC_PRODUCT_CLASS",
    )
    assert validation.marker_mismatches == ()
    assert validation.answer is not None
    assert "997351790000" in validation.answer
    assert "889429740000" in validation.answer
    assert "820108800000" in validation.answer
    assert "{{NUM_" not in validation.answer


def test_name_identifier_pair_inside_name_marker_is_accepted() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "상품명[Vanguard 500 Index Fund;ETF (VOO)]: {{NUM_001}}",
        ),
    )

    assert validation.accepted is True
    assert validation.answer == (
        "상품명[Vanguard 500 Index Fund;ETF (VOO)]: 997351790000"
    )
    assert validation.marker_mismatches == ()


def test_identifier_name_pair_is_accepted_for_the_same_product() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "VOO - Vanguard 500 Index Fund;ETF: {{NUM_001}}",
        ),
    )

    assert validation.accepted is True
    assert validation.answer == (
        "VOO - Vanguard 500 Index Fund;ETF: 997351790000"
    )
    assert validation.marker_mismatches == ()


@pytest.mark.parametrize(
    "answer",
    (
        "상품명: Vanguard 500 Index Fund;ETF (VOO): {{NUM_001}}",
        "상품ID: VOO - Vanguard 500 Index Fund;ETF: {{NUM_001}}",
    ),
)
def test_explicit_role_marker_accepts_same_product_pair(answer: str) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(SupportStatus.SUPPORTED, answer),
    )

    assert validation.accepted is True
    assert validation.marker_mismatches == ()


def test_explicit_role_marker_rejects_cross_product_pair() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "상품명: Vanguard 500 Index Fund;ETF (IVV): {{NUM_001}}",
        ),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        validation.reason
        is GenerationValidationReason.ENTITY_MARKER_ROLE_MISMATCH
    )
    assert any(
        mismatch.detection_rule == "PRODUCT_PAIR_MISMATCH"
        for mismatch in validation.marker_mismatches
    )


@pytest.mark.parametrize(
    ("name", "identifier"),
    (
        ("Vanguard 500 Index Fund;ETF", "IVV"),
        ("iShares Core S&P 500 ETF", "SPY"),
    ),
)
def test_cross_product_name_identifier_pair_is_rejected(
    name: str,
    identifier: str,
) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            f"{name} ({identifier}): {{{{NUM_001}}}}",
        ),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        validation.reason
        is GenerationValidationReason.ENTITY_MARKER_ROLE_MISMATCH
    )
    assert validation.marker_mismatches
    mismatch = validation.marker_mismatches[0]
    assert mismatch.detection_rule == "PRODUCT_PAIR_MISMATCH"
    assert mismatch.expected_role == "same_product_identifier"


def test_existing_marker_with_wrong_role_is_rejected_with_diagnostic() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "상품명[VOO]: {{NUM_001}}",
        ),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        validation.reason
        is GenerationValidationReason.ENTITY_MARKER_ROLE_MISMATCH
    )
    assert len(validation.marker_mismatches) == 1
    mismatch = validation.marker_mismatches[0]
    assert mismatch.marker_token == "{{E001}}"
    assert mismatch.placeholder_id == "E001"
    assert mismatch.declared_role == "product_name"
    assert mismatch.expected_role == "product_name"
    assert mismatch.actual_role == "product_identifier"
    assert mismatch.mapped_evidence_value == "VOO"
    assert mismatch.product_key == "VOO"
    assert mismatch.source_row_id == "srid:v1:live-named-001"
    assert mismatch.detection_rule == "MARKER_ROLE_MISMATCH"


def test_unknown_entity_marker_placeholder_is_rejected() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "상품명[{{E999}}]: {{NUM_001}}",
        ),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_ENTITY
    assert validation.reason is GenerationValidationReason.UNKNOWN_PLACEHOLDER


def test_result_count_is_allowed_only_when_derived_from_rows() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    accepted = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "3개 상품을 확인했습니다. {{NUM_001}}",
        ),
    )
    rejected = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "4개 상품을 확인했습니다. {{NUM_001}}",
        ),
    )

    assert accepted.accepted is True
    assert accepted.detected_number_spans == ("3",)
    assert accepted.number_classifications == ("RESULT_COUNT",)
    assert accepted.allowed_derived_numeric_values == ("1", "2", "3")
    assert rejected.status is GenerationValidationStatus.REJECTED_NUMBER
    assert rejected.number_classifications == ("UNAPPROVED_NUMBER",)


def test_structural_list_enumeration_is_allowed_for_all_result_rows() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "1. VOO\n2. IVV\n3. SPY",
        ),
    )

    assert validation.accepted is True
    assert validation.normalized_entity_literals == ("VOO", "IVV", "SPY")
    assert validation.detected_number_spans == ("1", "2", "3")
    assert validation.number_classifications == (
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
    )


@pytest.mark.parametrize(
    "answer",
    (
        "1. {{E001}}\n2. {{E004}}\n3. {{E007}}",
        "1) {{E001}}\n2) {{E004}}\n3) {{E007}}",
        "1.{{E001}}\r\n\r\n2.{{E004}}\r\n3.{{E007}}",
    ),
)
def test_complete_ordered_list_variants_are_allowed(answer: str) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(SupportStatus.SUPPORTED, answer),
    )

    assert validation.accepted is True
    assert validation.detected_number_spans == ("1", "2", "3")
    assert validation.number_classifications == (
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
    )


@pytest.mark.parametrize(
    "answer",
    (
        "1. {{E001}}\n2. {{E004}}\n4. {{E007}}",
        "1. {{E001}}\n3. {{E007}}",
        "1. {{E001}}\n1. {{E004}}\n2. {{E007}}",
        "1. {{E001}}\n2. {{E004}}\n3. {{E007}}\n4. {{E001}}",
        "본문 중 1 2 3",
    ),
)
def test_incomplete_or_non_structural_number_sequences_are_rejected(
    answer: str,
) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(SupportStatus.SUPPORTED, answer),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_NUMBER
    assert "UNAPPROVED_NUMBER" in validation.number_classifications


def test_result_count_and_complete_ordered_list_are_allowed_together() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "3개 상품을 확인했습니다.\n"
            "1. {{E001}}\n2. {{E004}}\n3. {{E007}}",
        ),
    )

    assert validation.accepted is True
    assert validation.detected_number_spans == ("3", "1", "2", "3")
    assert validation.number_classifications == (
        "RESULT_COUNT",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
    )


@pytest.mark.parametrize(
    "answer",
    (
        "3개는 다음과 같습니다. "
        "1. {{E001}} 항목 2. {{E004}} 항목 3. {{E007}} 항목",
        "3개는 다음과 같습니다. "
        "1) {{E001}} 항목 2) {{E004}} 항목 3) {{E007}} 항목",
    ),
)
def test_complete_inline_ordered_list_is_allowed(answer: str) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(SupportStatus.SUPPORTED, answer),
    )

    assert validation.accepted is True
    assert validation.enumeration_candidate_sequence == ("1", "2", "3")
    assert validation.detected_number_spans == ("3", "1", "2", "3")
    assert validation.number_classifications == (
        "RESULT_COUNT",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
    )


@pytest.mark.parametrize(
    "answer",
    (
        "1. 첫째 2. 둘째 4. 넷째",
        "1. 첫째 3. 셋째",
        "1. 첫째 2. 둘째 3. 셋째 4. 넷째",
    ),
)
def test_invalid_inline_ordered_list_sequence_is_rejected(answer: str) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(SupportStatus.SUPPORTED, answer),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_NUMBER
    assert "UNAPPROVED_NUMBER" in validation.number_classifications


def test_live_pref02_inline_enumeration_format_is_allowed() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "AUM이 큰 3개는 다음과 같습니다. "
            "1. {{E002}} (상품ID: {{E001}}) - AUM: {{NUM_001}}  "
            "2. {{E005}} (상품ID: {{E004}}) - AUM: {{NUM_002}}  "
            "3. {{E008}} (상품ID: {{E007}}) - AUM: {{NUM_003}}",
        ),
    )

    assert validation.accepted is True
    assert validation.enumeration_candidate_sequence == ("1", "2", "3")
    assert validation.number_classifications == (
        "RESULT_COUNT",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
        "LIST_ENUMERATION",
    )
    assert "{{E" not in validation.answer
    assert "{{NUM_" not in validation.answer


def test_number_contexts_explain_invalid_enumeration_without_raw_output() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "3개 상품입니다.\n1. {{E001}}\n2. {{E004}}\n4. {{E007}}",
        ),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_NUMBER
    assert validation.enumeration_candidate_sequence == ("1", "2", "4")
    assert tuple(context.span for context in validation.number_contexts) == (
        "3",
        "1",
        "2",
        "4",
    )
    assert validation.number_contexts[0].is_list_candidate is False
    assert (
        validation.number_contexts[0].candidate_rejection_reason
        == "UNSUPPORTED_ENUMERATION_MARKER"
    )
    assert all(
        context.is_list_candidate
        and context.candidate_rejection_reason
        == "SEQUENCE_NOT_EXACT_1_TO_RESULT_COUNT"
        for context in validation.number_contexts[1:]
    )
    assert tuple(context.line_index for context in validation.number_contexts) == (
        1,
        2,
        3,
        4,
    )
    assert all(len(context.line_prefix) <= 20 for context in validation.number_contexts)
    assert all(
        len(context.structural_context) <= 41
        for context in validation.number_contexts
    )


def test_exact_evidence_numeric_value_is_allowed() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "Vanguard 500 Index Fund;ETF의 AUM은 997351790000입니다.",
        ),
    )

    assert validation.accepted is True
    assert validation.detected_number_spans == ("997351790000",)
    assert validation.normalized_number_spans == ("997351790000",)
    assert validation.number_classifications == ("EVIDENCE_NUMERIC_VALUE",)
    assert validation.allowed_evidence_numeric_values == (
        "997351790000",
        "889429740000",
        "820108800000",
    )


@pytest.mark.parametrize(
    "answer",
    (
        "수익률 12.5%입니다. {{NUM_001}}",
        "AUM은 100억입니다. {{E002}}",
        "AUM은 997조입니다. {{E002}}",
        "AUM은 3,519억입니다. {{E002}}",
    ),
)
def test_unapproved_financial_numbers_remain_rejected(answer: str) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(SupportStatus.SUPPORTED, answer),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_NUMBER
    assert "UNAPPROVED_NUMBER" in validation.number_classifications


def test_unapproved_ticker_and_product_remain_rejected() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "Invesco QQQ Trust (QQQ)도 함께 확인했습니다. {{NUM_001}}",
        ),
    )

    assert validation.accepted is False
    assert validation.status is GenerationValidationStatus.REJECTED_ENTITY
    assert validation.reason is GenerationValidationReason.UNMARKED_IDENTIFIER


@pytest.mark.parametrize("placeholder", ("{{NUM_099}}", "{{NUM-1}}"))
def test_unknown_or_malformed_numeric_placeholder_is_rejected(
    placeholder: str,
) -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            f"Vanguard 500 Index Fund;ETF의 AUM은 {placeholder}입니다.",
        ),
    )

    assert validation.status is GenerationValidationStatus.REJECTED_ENTITY
    assert validation.reason is GenerationValidationReason.UNKNOWN_PLACEHOLDER

def test_fuzzy_product_entity_is_not_treated_as_exact_evidence() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "검증형 ETF의 값은 {{NUM_001}}입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        result.validation_reason
        is GenerationValidationReason.UNMARKED_PRODUCT_REFERENCE
    )


def test_partial_evidence_name_with_an_extra_token_is_rejected() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "검증 ETF Plus의 값은 {{NUM_001}}입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        result.validation_reason
        is GenerationValidationReason.UNMARKED_PRODUCT_REFERENCE
    )


def test_rejection_preserves_prior_exact_normalization_diagnostics() -> None:
    generation_input = _input()
    prompt = build_evidence_only_prompt(generation_input)
    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "검증 ETF의 값과 검증 ETFPlus를 비교했습니다.",
        ),
    )

    assert validation.accepted is False
    assert validation.status is GenerationValidationStatus.REJECTED_ENTITY
    assert validation.reason is GenerationValidationReason.LITERAL_EVIDENCE_ENTITY
    assert validation.normalized_entity_literals == ("검증 ETF",)
    assert validation.residual_entity_literals == ("검증 ETF",)

def test_markdown_json_wrapper_is_normalized_without_semantic_changes() -> None:
    answer_json = _json(
        SupportStatus.SUPPORTED,
        "상품명[{{E002}}]의 값은 {{NUM_001}}입니다.",
    )
    transport, result = _generate(f"```json\n{answer_json}\n```")

    assert result.answer == "상품명[검증 ETF]의 값은 30입니다."
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.ACCEPTED
    assert (
        result.validation_reason
        is GenerationValidationReason.MARKDOWN_JSON_WRAPPER
    )
    assert len(transport.prompts) == 1


def test_format_repair_succeeds_once_and_still_requires_validation() -> None:
    invalid_shape = json.dumps(
        {
            "status": "SUPPORTED",
            "answer": "상품명[{{E002}}]의 값은 {{NUM_001}}입니다.",
            "explanation": "remove this wrapper field",
        },
        ensure_ascii=False,
    )
    repaired = _json(
        SupportStatus.SUPPORTED,
        "상품명[{{E002}}]의 값은 {{NUM_001}}입니다.",
    )
    transport = SequenceTransport((invalid_shape, repaired))

    result = asyncio.run(HyperClovaAnswerGenerator(transport).generate(_input()))

    assert result.answer == "상품명[검증 ETF]의 값은 30입니다."
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.ACCEPTED
    assert (
        result.validation_reason
        is GenerationValidationReason.FORMAT_REPAIR_ACCEPTED
    )
    assert len(transport.prompts) == 2
    assert "[FORMAT_REPAIR]" not in transport.prompts[0]
    assert "[FORMAT_REPAIR]" in transport.prompts[1]


def test_format_repair_applies_exact_evidence_literal_normalization() -> None:
    invalid_shape = json.dumps(
        {"status": "SUPPORTED", "answer": "형식 오류", "extra": True},
        ensure_ascii=False,
    )
    repaired = _json(
        SupportStatus.SUPPORTED,
        "**검증 ETF** (ETF001)의 값은 {{NUM_001}}입니다.",
    )
    transport = SequenceTransport((invalid_shape, repaired))

    result = asyncio.run(HyperClovaAnswerGenerator(transport).generate(_input()))

    assert result.answer == "**검증 ETF** (ETF001)의 값은 30입니다."
    assert result.used_fallback is False
    assert result.validation_status is GenerationValidationStatus.ACCEPTED
    assert (
        result.validation_reason
        is GenerationValidationReason.FORMAT_REPAIR_ACCEPTED
    )
    assert len(transport.prompts) == 2


def test_format_repair_failure_keeps_safe_fallback() -> None:
    invalid_shape = json.dumps(
        {"status": "SUPPORTED", "answer": "형식 오류", "extra": True},
        ensure_ascii=False,
    )
    hallucinated = _json(
        SupportStatus.SUPPORTED,
        "상품명[가짜 ETF]의 값은 {{NUM_001}}입니다.",
    )
    transport = SequenceTransport((invalid_shape, hallucinated))

    result = asyncio.run(HyperClovaAnswerGenerator(transport).generate(_input()))

    assert result.answer == _input().deterministic_fallback_answer
    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        result.validation_reason
        is GenerationValidationReason.ENTITY_MARKER_ROLE_MISMATCH
    )
    assert len(transport.prompts) == 2


def test_repeated_malformed_output_uses_fallback_after_one_repair() -> None:
    transport = SequenceTransport(("not-json", "still-not-json"))

    result = asyncio.run(HyperClovaAnswerGenerator(transport).generate(_input()))

    assert result.answer == _input().deterministic_fallback_answer
    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_FORMAT
    assert result.validation_reason is GenerationValidationReason.NON_JSON_OUTPUT
    assert len(transport.prompts) == 2


def test_prompt_contains_only_bounded_evidence_contract() -> None:
    prompt = build_evidence_only_prompt(_input()).text

    assert "제공된 evidence만 사용" in prompt
    assert '"source_field":"pd_nm#1"' in prompt
    assert '"value":"검증 ETF"' in prompt
    assert '"placeholder":"{{NUM_001}}"' in prompt
    assert '"value":"{{NUM_001}}"' in prompt
    assert '"value":"30"' not in prompt
    assert "숫자를 계산·변환·축약·반올림하지 마세요" in prompt
    assert "억·조·만 등의 단위로 환산하지 마세요" in prompt
    assert "raw_record" not in prompt
    assert "raw_value" not in prompt
    assert "profiling" not in prompt
    assert "투자 권유" in prompt


def test_three_numeric_placeholders_restore_exact_normalized_values() -> None:
    generation_input = _input(evidence=_live_named_product_evidence())
    prompt = build_evidence_only_prompt(generation_input)
    numeric_placeholders = tuple(
        placeholder
        for placeholder in prompt.placeholders
        if placeholder.token.startswith("{{NUM_")
    )
    entity_placeholders = tuple(
        placeholder
        for placeholder in prompt.placeholders
        if placeholder.role in {"product_name", "product_identifier"}
    )

    assert tuple(item.token for item in numeric_placeholders) == (
        "{{NUM_001}}",
        "{{NUM_002}}",
        "{{NUM_003}}",
    )
    assert tuple(item.value for item in numeric_placeholders) == (
        "997351790000",
        "889429740000",
        "820108800000",
    )
    assert tuple(item.token for item in entity_placeholders) == (
        "{{E001}}",
        "{{E002}}",
        "{{E004}}",
        "{{E005}}",
        "{{E007}}",
        "{{E008}}",
    )
    assert tuple(
        (item.role, item.product_key, item.source_row_id)
        for item in entity_placeholders
    ) == (
        ("product_identifier", "VOO", "srid:v1:live-named-001"),
        ("product_name", "VOO", "srid:v1:live-named-001"),
        ("product_identifier", "IVV", "srid:v1:live-named-002"),
        ("product_name", "IVV", "srid:v1:live-named-002"),
        ("product_identifier", "SPY", "srid:v1:live-named-003"),
        ("product_name", "SPY", "srid:v1:live-named-003"),
    )
    assert all(item.value not in prompt.text for item in numeric_placeholders)

    validation = PostGenerationValidator().validate(
        generation_input,
        prompt,
        _json(
            SupportStatus.SUPPORTED,
            "{{NUM_001}}, {{NUM_002}}, {{NUM_003}}",
        ),
    )

    assert validation.accepted is True
    assert validation.answer == "997351790000, 889429740000, 820108800000"
    assert "{{NUM_" not in validation.answer


def test_unknown_product_name_uses_deterministic_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품명[가짜 ETF]의 값은 {{NUM_001}}입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        result.validation_reason
        is GenerationValidationReason.ENTITY_MARKER_ROLE_MISMATCH
    )
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
            "상품명[{{E002}}]의 값은 {{NUM_001}}억입니다.",
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
        assert (
            result.validation_reason
            is GenerationValidationReason.TRANSPORT_EXCEPTION
        )

    timed_out = asyncio.run(
        HyperClovaAnswerGenerator(
            HangingTransport(),
            timeout_seconds=0.001,
        ).generate(_input())
    )
    assert timed_out.used_fallback is True
    assert timed_out.validation_status is GenerationValidationStatus.TRANSPORT_ERROR
    assert (
        timed_out.validation_reason
        is GenerationValidationReason.TRANSPORT_EXCEPTION
    )


def test_unmarked_unknown_product_reference_uses_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "가짜 ETF는 검증된 결과입니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        result.validation_reason
        is GenerationValidationReason.UNMARKED_PRODUCT_REFERENCE
    )


def test_unsupported_qualitative_financial_claim_uses_fallback() -> None:
    _transport, result = _generate(
        _json(
            SupportStatus.SUPPORTED,
            "상품명[{{E002}}]은 수익률 전망이 좋습니다.",
        )
    )

    assert result.used_fallback is True
    assert result.validation_status is GenerationValidationStatus.REJECTED_ENTITY
    assert (
        result.validation_reason
        is GenerationValidationReason.UNSUPPORTED_FINANCIAL_CLAIM
    )


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
            "상품명[{{E002}}] (상품ID[{{E001}}])의 값은 {{NUM_001}}입니다.",
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
