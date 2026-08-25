"""Answer generators with deterministic fail-closed fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from time import monotonic
from typing import Protocol

from app.llm.hcx_client import HCXClient

from .contracts import (
    GenerationInput,
    GenerationResult,
    GenerationValidationStatus,
)
from .prompts import build_evidence_only_prompt
from .validator import PostGenerationValidator


class AnswerGenerator(Protocol):
    def generate(self, generation_input: GenerationInput) -> Awaitable[GenerationResult]: ...


class DeterministicAnswerGenerator:
    """Return the already validated deterministic renderer output unchanged."""

    async def generate(self, generation_input: GenerationInput) -> GenerationResult:
        return GenerationResult(
            answer=generation_input.deterministic_fallback_answer,
            provider="deterministic",
            used_fallback=False,
            validation_status=GenerationValidationStatus.DETERMINISTIC,
            elapsed_ms=0.0,
        )


class HyperClovaAnswerGenerator:
    """Generate from evidence only and fall back on every unsafe outcome."""

    def __init__(
        self,
        transport: HCXClient,
        *,
        validator: PostGenerationValidator | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not 0 < timeout_seconds <= 60:
            raise ValueError("generation timeout must be between 0 and 60 seconds")
        self._transport = transport
        self._validator = validator or PostGenerationValidator()
        self._timeout_seconds = timeout_seconds

    def _fallback(
        self,
        generation_input: GenerationInput,
        status: GenerationValidationStatus,
        started_at: float,
    ) -> GenerationResult:
        return GenerationResult(
            answer=generation_input.deterministic_fallback_answer,
            provider="hyperclova-x",
            used_fallback=True,
            validation_status=status,
            elapsed_ms=max(0.0, (monotonic() - started_at) * 1000),
        )

    async def generate(self, generation_input: GenerationInput) -> GenerationResult:
        started_at = monotonic()
        prompt = build_evidence_only_prompt(generation_input)
        try:
            raw_output = await asyncio.wait_for(
                self._transport.generate(prompt.text),
                timeout=self._timeout_seconds,
            )
        except Exception:
            return self._fallback(
                generation_input,
                GenerationValidationStatus.TRANSPORT_ERROR,
                started_at,
            )
        validation = self._validator.validate(generation_input, prompt, raw_output)
        if not validation.accepted or validation.answer is None:
            return self._fallback(generation_input, validation.status, started_at)
        return GenerationResult(
            answer=validation.answer,
            provider="hyperclova-x",
            used_fallback=False,
            validation_status=validation.status,
            elapsed_ms=max(0.0, (monotonic() - started_at) * 1000),
        )


__all__ = [
    "AnswerGenerator",
    "DeterministicAnswerGenerator",
    "HyperClovaAnswerGenerator",
]
