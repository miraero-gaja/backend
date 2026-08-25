"""Conservative deterministic validation of model-generated answers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .contracts import GenerationInput, GenerationValidationStatus
from .prompts import EvidenceOnlyPrompt, EvidencePlaceholder


_PLACEHOLDER = re.compile(r"\{\{E\d{3}\}\}")
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_])"
)
_IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9._-]*[A-Za-z])(?=[A-Za-z0-9._-]*\d)[A-Za-z0-9._-]+\b")
_FINANCIAL_UNIT = re.compile(
    r"(?<![가-힣A-Za-z])(?:퍼센트|억원|백만원|만원|천원|원|억|%)"
    r"(?=$|[\s.,;:!?)]|은|는|이|가|을|를|으로|입니다)"
)
_RECOMMENDATION = re.compile(
    r"추천|투자\s*(?:하세요|권유|권합니다)|매수|매도|선택하세요|권합니다"
)
_NAME_MARKER = re.compile(r"상품명\[([^\]]*)\]")
_IDENTIFIER_MARKER = re.compile(r"상품ID\[([^\]]*)\]")
_EXPLICIT_ENTITY_LABEL = re.compile(r"(?:상품명|상품ID|상품번호)\s*[:=]")
_UNMARKED_PRODUCT_REFERENCE = re.compile(
    r"[가-힣A-Za-z][가-힣A-Za-z0-9&._-]*"
    r"(?:\s+[가-힣A-Za-z0-9&._-]+){0,3}\s*(?:ETF|펀드|채권)"
    r"(?=$|[\s,.;:!?)]|은|는|이|가|을|를|의|에서)"
)
_UNSUPPORTED_FINANCIAL_CLAIM = re.compile(
    r"수익률|수익성|전망|예상|보장|저평가|고평가|투자매력|"
    r"안전(?:하다|합니다|한)|우수(?:하다|합니다|한)|유리(?:하다|합니다|한)|"
    r"상승(?:한다|합니다|할)|하락(?:한다|합니다|할)"
)


@dataclass(frozen=True, slots=True)
class PostGenerationValidation:
    status: GenerationValidationStatus
    answer: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status is GenerationValidationStatus.ACCEPTED


def _placeholder_map(
    prompt: EvidenceOnlyPrompt,
) -> dict[str, EvidencePlaceholder]:
    return {placeholder.token: placeholder for placeholder in prompt.placeholders}


def _markers_are_approved(
    template: str,
    placeholders: dict[str, EvidencePlaceholder],
) -> bool:
    for marker, expected_role in (
        (_NAME_MARKER, "product_name"),
        (_IDENTIFIER_MARKER, "product_identifier"),
    ):
        for match in marker.finditer(template):
            placeholder = placeholders.get(match.group(1))
            if placeholder is None or placeholder.role != expected_role:
                return False
    return _EXPLICIT_ENTITY_LABEL.search(template) is None


class PostGenerationValidator:
    """Accept only status-preserving, placeholder-grounded model output."""

    def validate(
        self,
        generation_input: GenerationInput,
        prompt: EvidenceOnlyPrompt,
        raw_output: str,
    ) -> PostGenerationValidation:
        if not isinstance(raw_output, str) or not raw_output.strip():
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_EMPTY)
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_FORMAT)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"status", "answer"}
            or not isinstance(payload.get("status"), str)
            or not isinstance(payload.get("answer"), str)
        ):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_FORMAT)
        if payload["status"] != generation_input.support_status.value:
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_STATUS)

        template = payload["answer"].strip()
        if not template:
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_EMPTY)
        if _RECOMMENDATION.search(template):
            return PostGenerationValidation(
                GenerationValidationStatus.REJECTED_RECOMMENDATION
            )

        placeholders = _placeholder_map(prompt)
        used_tokens = tuple(_PLACEHOLDER.findall(template))
        if any(token not in placeholders for token in used_tokens):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_ENTITY)
        if not _markers_are_approved(template, placeholders):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_ENTITY)
        scrubbed = _PLACEHOLDER.sub("", template)

        entity_values = {
            placeholder.value
            for placeholder in placeholders.values()
            if placeholder.role in {"product_name", "product_identifier"}
        }
        if any(value and value in scrubbed for value in entity_values):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_ENTITY)
        if _IDENTIFIER.search(scrubbed):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_ENTITY)
        if _UNMARKED_PRODUCT_REFERENCE.search(scrubbed):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_ENTITY)
        if _UNSUPPORTED_FINANCIAL_CLAIM.search(scrubbed):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_ENTITY)
        if _NUMBER.search(scrubbed):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_NUMBER)

        allowed_units = {
            item.unit for item in generation_input.evidence if item.unit is not None
        }
        units = set(_FINANCIAL_UNIT.findall(scrubbed))
        if units - allowed_units:
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_UNIT)

        if (
            generation_input.support_status.value in {"SUPPORTED", "PARTIAL"}
            and (
                generation_input.evidence
                or generation_input.aggregate_evidence
            )
            and not used_tokens
        ):
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_FORMAT)

        if generation_input.support_status.value in {"UNSUPPORTED", "NO_MATCH"}:
            if used_tokens or _NAME_MARKER.search(template) or _IDENTIFIER_MARKER.search(template):
                return PostGenerationValidation(GenerationValidationStatus.REJECTED_ENTITY)

        answer = template
        for token in used_tokens:
            answer = answer.replace(token, placeholders[token].value)
        if not answer or len(answer) > 1000:
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_FORMAT)
        return PostGenerationValidation(
            GenerationValidationStatus.ACCEPTED,
            answer=answer,
        )


__all__ = ["PostGenerationValidation", "PostGenerationValidator"]
