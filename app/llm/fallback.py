"""Deterministic public fallbacks for unsupported and missing-input paths."""

from app.core.constants import UNSUPPORTED_ANSWER, missing_input_answer


def safe_fallback(missing_inputs: tuple[str, ...] = ()) -> str:
    return missing_input_answer(missing_inputs) if missing_inputs else UNSUPPORTED_ANSWER

