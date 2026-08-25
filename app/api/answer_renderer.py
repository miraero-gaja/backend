"""Bounded deterministic rendering from validated evidence to public strings."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.contracts import QueryContract
from app.core.constants import (
    UNSUPPORTED_ANSWER,
    missing_input_answer,
    missing_input_trace,
)
from app.evidence.models import ReasonCode, SupportDecision, SupportStatus
from app.evidence.serializer import serialize_evidence
from mappings.semantic import get_semantic_field_approval


MAX_THINK_TRACE_CHARS = 200
MAX_ANSWER_CHARS = 1000
MAX_ANSWER_VALUES = 10


@dataclass(frozen=True, slots=True)
class RenderedAnswer:
    retrieved_context: str
    think_trace: str
    answer: str


_REASON_TRACE = {
    "unit_conversion_not_approved": "단위/scale 미승인",
    "semantic_operation_not_open": "요청 연산 CLOSED",
    "semantic_concept_not_confirmed": "concept 미확정",
    "semantic_field_distinction_unapproved": "field 의미 구분 미확정",
    "semantic_field_not_recognized": "승인 field 없음",
    "unknown_semantic_key": "semantic key 미승인",
    "filtered_aggregation_not_supported": "집계 조합 미지원",
    "query_operation_not_recognized": "연산 표현 미확정",
    "product_scope_missing": "상품군 파싱 실패",
    "multiple_product_scopes": "상품군 모호성 확인",
}

_REASON_ANSWER = {
    "unit_conversion_not_approved": (
        "요청한 단위 또는 scale이 승인되지 않아 현재 확인할 수 없습니다."
    ),
    "semantic_operation_not_open": (
        "요청한 연산은 현재 semantic approval에서 허용되지 않아 확인할 수 없습니다."
    ),
    "semantic_concept_not_confirmed": (
        "요청한 금융 의미가 공식적으로 확정되지 않아 현재 확인할 수 없습니다."
    ),
    "semantic_field_distinction_unapproved": (
        "요청한 field들의 금융적 의미 구분이 확정되지 않아 현재 확인할 수 없습니다."
    ),
    "semantic_field_not_recognized": (
        "요청한 항목은 현재 승인된 structured field로 확인할 수 없습니다."
    ),
    "unknown_semantic_key": (
        "요청한 semantic field가 승인 registry에 없어 현재 확인할 수 없습니다."
    ),
    "filtered_aggregation_not_supported": (
        "요청한 조건부 집계는 현재 지원 범위가 아니어서 확인할 수 없습니다."
    ),
    "query_operation_not_recognized": (
        "요청한 계산 또는 정렬 연산을 확정할 수 없어 현재 확인할 수 없습니다."
    ),
}


def _bounded_steps(steps: list[str]) -> str:
    compact = [step.strip() for step in steps if step.strip()]
    while len(" → ".join(compact)) > MAX_THINK_TRACE_CHARS and len(compact) > 2:
        compact.pop(-2)
    rendered = " → ".join(compact)
    return rendered[:MAX_THINK_TRACE_CHARS]


def _reason(query: QueryContract) -> str | None:
    understanding = query.understanding
    if understanding is None:
        return None
    if understanding.unsupported_reason:
        return understanding.unsupported_reason
    return understanding.ambiguity[0] if understanding.ambiguity else None


def _trace(query: QueryContract, decision: SupportDecision) -> str:
    if query.required_inputs:
        return missing_input_trace(query.required_inputs)

    understanding = query.understanding
    reason = _reason(query)
    steps = ["입력 검증"]
    if understanding is not None:
        if understanding.product_candidate:
            steps.append(f"상품군: {understanding.product_candidate}")
        elif reason in {"product_scope_missing", "multiple_product_scopes"}:
            steps.append(_REASON_TRACE[reason])
        if understanding.requested_field_alias:
            steps.append(f"{understanding.requested_field_alias} grounding")
        if understanding.sort_direction is not None:
            steps.append(f"SORT_{understanding.sort_direction.value} 승인")
        if understanding.limit is not None:
            steps.append(f"Top {understanding.limit} 실행")

    if decision.status is SupportStatus.SUPPORTED:
        steps.extend(("Structured 실행 성공", "Evidence 검증", "SUPPORTED"))
    elif decision.status is SupportStatus.NO_MATCH:
        steps.extend(("Structured 정상 실행", "0건 반환", "NO_MATCH"))
    elif decision.status is SupportStatus.PARTIAL:
        steps.extend(("일부 Evidence 검증", "PARTIAL"))
    elif ReasonCode.TOOL_FAILURE in decision.reason_codes:
        steps.extend(("Structured 조회 실패", "TOOL_FAILURE"))
    else:
        reason_trace = _REASON_TRACE.get(
            reason or "",
            "승인된 데이터 소스/의미 없음",
        )
        if reason_trace not in steps:
            steps.append(reason_trace)
        if reason in {"product_scope_missing", "multiple_product_scopes"}:
            steps.append("승인된 데이터 소스 없음")
        steps.append("UNSUPPORTED")
    return _bounded_steps(steps)


def _display_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    rendered = str(value)
    return rendered if len(rendered) <= 80 else f"{rendered[:77]}..."


def _supported_answer(query: QueryContract, decision: SupportDecision) -> str:
    understanding = query.understanding
    product = (
        understanding.product_candidate
        if understanding is not None and understanding.product_candidate
        else "선택한 상품군"
    )
    if decision.aggregate_evidence:
        aggregate = decision.aggregate_evidence[0]
        return (
            f"{product}에서 검증된 전체 상품 개수는 "
            f"{aggregate.value}개입니다."
        )[:MAX_ANSWER_CHARS]
    field = (
        understanding.requested_field_alias
        if understanding is not None and understanding.requested_field_alias
        else "요청 field"
    )
    row_count = len({item.source_row_id for item in decision.evidence})
    structured_query = query.structured_query
    semantic_keys = (
        understanding.semantic_keys
        if understanding is not None
        else ()
    )
    requested_key = semantic_keys[0] if len(semantic_keys) == 1 else None
    table = structured_query.product_scope if structured_query is not None else None
    approvals = {
        key: get_semantic_field_approval(table, key)
        for key in (
            "pref02.product_identifier",
            "pref02.product_name",
            requested_key,
        )
        if table is not None and key is not None
    }
    fields = {
        key: approval.qualified_name
        for key, approval in approvals.items()
        if approval is not None
    }
    by_row: dict[str, dict[str, object]] = {}
    for item in decision.evidence:
        by_row.setdefault(item.source_row_id, {})[item.source_field] = (
            item.normalized_value
        )

    values: list[str] = []
    metric_field = fields.get(requested_key) if requested_key is not None else None
    for row in tuple(by_row.values())[:MAX_ANSWER_VALUES]:
        metric = row.get(metric_field) if metric_field is not None else None
        identifier = row.get(fields.get("pref02.product_identifier", ""))
        name = row.get(fields.get("pref02.product_name", ""))
        label_parts = []
        if isinstance(name, str) and name.strip():
            label_parts.append(name)
        if isinstance(identifier, str) and identifier.strip():
            label_parts.append(f"({identifier})" if label_parts else identifier)
        if label_parts and metric_field is not None:
            values.append(
                f"{' '.join(label_parts)} | {field} source-native 값: "
                f"{_display_value(metric)}"
            )

    if not values:
        values = [
            _display_value(item.normalized_value)
            for item in decision.evidence[:MAX_ANSWER_VALUES]
        ]
    suffix = "" if len(by_row) <= MAX_ANSWER_VALUES else ", ..."
    rendered = (
        f"{product}에서 검증된 {field} 결과 {row_count}건을 확인했습니다. "
        f"source-native 값(단위 변환 없음): {'; '.join(values)}{suffix}."
    )
    return rendered[:MAX_ANSWER_CHARS]


class DeterministicAnswerRenderer:
    """Render only approved evidence and typed failure states; never call an LLM."""

    def render(
        self,
        query: QueryContract,
        decision: SupportDecision,
    ) -> RenderedAnswer:
        reason = _reason(query)
        retrieved_context = serialize_evidence(
            decision,
            unsupported_reason=reason,
        )
        think_trace = _trace(query, decision)

        if query.required_inputs:
            answer = missing_input_answer(query.required_inputs)
        elif decision.status is SupportStatus.SUPPORTED and (
            decision.evidence or decision.aggregate_evidence
        ):
            answer = _supported_answer(query, decision)
        elif decision.status is SupportStatus.NO_MATCH:
            answer = (
                "승인된 조건으로 정상 조회했지만 조건에 맞는 상품을 "
                "확인할 수 없습니다."
            )
        elif decision.status is SupportStatus.PARTIAL:
            supported_count = sum(
                item.decision is SupportStatus.SUPPORTED
                for item in decision.evidence
            )
            answer = (
                f"요청 전체는 확인할 수 없지만 검증 가능한 근거 "
                f"{supported_count}건을 확인했습니다."
            )
        elif ReasonCode.TOOL_FAILURE in decision.reason_codes:
            answer = "시스템 조회 실패로 현재 결과를 확인할 수 없습니다."
        else:
            answer = _REASON_ANSWER.get(reason or "", UNSUPPORTED_ANSWER)

        return RenderedAnswer(
            retrieved_context=retrieved_context,
            think_trace=think_trace,
            answer=answer[:MAX_ANSWER_CHARS],
        )


__all__ = [
    "DeterministicAnswerRenderer",
    "MAX_ANSWER_CHARS",
    "MAX_THINK_TRACE_CHARS",
    "RenderedAnswer",
]
