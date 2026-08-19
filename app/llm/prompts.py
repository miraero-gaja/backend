"""Evidence-only prompt construction reserved for future HCX integration."""


def build_grounded_prompt(*, question: str, retrieved_context: str) -> str:
    if retrieved_context.startswith("no-evidence"):
        raise ValueError("a generation prompt requires validated evidence")
    return (
        "검증된 근거에 포함된 사실만 사용해 답변하세요. "
        "근거에 없는 상품명이나 수치를 생성하지 마세요.\n"
        f"질문: {question}\n검증된 근거: {retrieved_context}"
    )

