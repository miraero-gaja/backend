"""Stable public strings and runtime identifiers for the safe skeleton."""

NO_EVIDENCE_CONTEXT = "no-evidence | backend-skeleton"
UNSUPPORTED_TRACE = "입력 검증 → 데이터 소스 미연결 확인 → Unsupported 처리"
UNSUPPORTED_ANSWER = (
    "현재 검증 가능한 금융상품 데이터가 연결되지 않아 답변을 확인할 수 없습니다."
)


def missing_input_trace(missing_fields: tuple[str, ...]) -> str:
    """Return a public execution summary without exposing private reasoning."""

    fields = ", ".join(missing_fields)
    return f"입력 검증 → 필수 입력값 누락({fields}) 확인 → Unsupported 처리"


def missing_input_answer(missing_fields: tuple[str, ...]) -> str:
    """Return a deterministic fallback that identifies missing API inputs."""

    fields = ", ".join(missing_fields)
    return f"필수 입력값이 누락되어 요청을 처리할 수 없습니다: {fields}."
