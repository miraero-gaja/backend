"""Bounded evidence-only prompt construction for HyperCLOVA X."""

from __future__ import annotations

import json
from dataclasses import dataclass

from mappings.core import get_confirmed_field_map
from mappings.semantic import get_table_semantic_approvals

from .contracts import GenerationInput


MAX_PROMPT_QUESTION_CHARS = 2000


@dataclass(frozen=True, slots=True)
class EvidencePlaceholder:
    token: str
    value: str
    role: str


@dataclass(frozen=True, slots=True)
class EvidenceOnlyPrompt:
    text: str
    placeholders: tuple[EvidencePlaceholder, ...]


def _role(source_table: str, source_field: str) -> str:
    semantic_approvals = get_table_semantic_approvals(source_table)
    for approval in semantic_approvals:
        if approval.qualified_name != source_field:
            continue
        if approval.semantic_key.endswith(".product_name"):
            return "product_name"
        if approval.semantic_key.endswith(".product_identifier"):
            return "product_identifier"

    for mapping in get_confirmed_field_map(source_table).values():
        if mapping.qualified_name != source_field:
            continue
        if mapping.semantic_field_key.endswith(".product_name"):
            return "product_name"
        if mapping.semantic_field_key.endswith(
            (".product_code", ".mirae_product_code")
        ):
            return "product_identifier"
    return "fact"


def build_evidence_only_prompt(generation_input: GenerationInput) -> EvidenceOnlyPrompt:
    """Serialize only approved evidence; never include raw rows or artifacts."""

    placeholders: list[EvidencePlaceholder] = []
    records: list[dict[str, object]] = []
    for index, item in enumerate(generation_input.evidence, start=1):
        value = "null" if item.normalized_value is None else str(item.normalized_value)
        placeholder = EvidencePlaceholder(
            token=f"{{{{E{index:03d}}}}}",
            value=value,
            role=_role(item.source_table, item.source_field),
        )
        placeholders.append(placeholder)
        record: dict[str, object] = {
            "placeholder": placeholder.token,
            "role": placeholder.role,
            "product_key": item.product_key,
            "source_table": item.source_table,
            "source_field": item.source_field,
            "value": value,
        }
        if item.unit is not None:
            record["unit"] = item.unit
        if item.snapshot is not None:
            record["snapshot"] = item.snapshot
        if item.effective_date is not None:
            record["effective_date"] = item.effective_date.isoformat()
        records.append(record)

    evidence_json = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    reasons = ",".join(reason.value for reason in generation_input.reason_codes)
    question = generation_input.question[:MAX_PROMPT_QUESTION_CHARS]
    text = (
        "[SYSTEM]\n"
        "당신은 검증된 금융상품 Evidence를 설명하는 한국어 답변 생성기입니다.\n"
        "검색, 계산, 필터, 정렬을 수행하지 마세요. 제공된 evidence만 사용하세요.\n"
        "evidence에 없는 사실, 상품명, 식별자, 숫자를 추가하지 마세요.\n"
        "수익률 전망, 투자 권유, 추천을 하지 마세요.\n"
        "미확정 unit, scale, code 의미를 추측하지 마세요.\n"
        "상품명은 상품명[placeholder], 식별자는 상품ID[placeholder], 수치는 "
        "placeholder를 그대로 사용하세요. placeholder 밖에 숫자나 금융 단위를 "
        "쓰지 마세요.\n"
        "입력 status를 바꾸지 말고 간결하게 답하세요.\n"
        "출력은 markdown 없이 정확히 "
        '{"status":"<입력 status>","answer":"<한국어 답변>"} JSON만 반환하세요.\n'
        "[INPUT]\n"
        f"status={generation_input.support_status.value}\n"
        f"reason_codes={reasons}\n"
        f"execution_trace={generation_input.execution_trace}\n"
        f"question={question}\n"
        f"evidence={evidence_json}"
    )
    return EvidenceOnlyPrompt(text=text, placeholders=tuple(placeholders))


__all__ = [
    "EvidenceOnlyPrompt",
    "EvidencePlaceholder",
    "MAX_PROMPT_QUESTION_CHARS",
    "build_evidence_only_prompt",
]
