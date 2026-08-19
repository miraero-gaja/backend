"""Last-line guard preventing unsupported model text from reaching the API."""

from app.evidence.models import SupportDecision, SupportStatus
from app.llm.fallback import safe_fallback


class AnswerGuard:
    def guard(
        self,
        candidate: str | None,
        decision: SupportDecision,
        *,
        missing_inputs: tuple[str, ...] = (),
    ) -> str:
        if (
            decision.status is not SupportStatus.SUPPORTED
            or not decision.evidence
            or candidate is None
            or not candidate.strip()
        ):
            return safe_fallback(missing_inputs)
        return candidate.strip()

