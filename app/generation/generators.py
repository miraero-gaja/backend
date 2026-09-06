"""Answer generators with deterministic fail-closed fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from time import monotonic
from typing import Protocol

from app.llm.hcx_client import HCXClient, HCXTransportError

from .contracts import (
    GenerationInput,
    GenerationResult,
    GenerationValidationReason,
    GenerationValidationStatus,
)
from .prompts import build_evidence_only_prompt, build_format_repair_prompt
from .validator import PostGenerationValidator


HCX_GENERATION_TIMEOUT_SECONDS = 10.0


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
        timeout_seconds: float = HCX_GENERATION_TIMEOUT_SECONDS,
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
        reason: GenerationValidationReason | None = None,
        transport_error: HCXTransportError | None = None,
        unexpected_exception_class: str | None = None,
    ) -> GenerationResult:
        return GenerationResult(
            answer=generation_input.deterministic_fallback_answer,
            provider="hyperclova_x",
            used_fallback=True,
            validation_status=status,
            validation_reason=reason,
            transport_error_code=(
                transport_error.code if transport_error is not None else None
            ),
            transport_exception_class=(
                transport_error.exception_class
                if transport_error is not None
                else unexpected_exception_class
            ),
            transport_http_status=(
                transport_error.http_status if transport_error is not None else None
            ),
            transport_ncp_status_code=(
                transport_error.ncp_status_code
                if transport_error is not None
                else None
            ),
            elapsed_ms=max(0.0, (monotonic() - started_at) * 1000),
        )

    @staticmethod
    def _transport_reason(error: HCXTransportError) -> GenerationValidationReason:
        if error.code == "HCX_OPEN_TIMEOUT":
            return GenerationValidationReason.TRANSPORT_OPEN_TIMEOUT
        if error.code == "HCX_READ_TIMEOUT":
            return GenerationValidationReason.TRANSPORT_READ_TIMEOUT
        if error.code == "HCX_HTTP_ERROR":
            return GenerationValidationReason.TRANSPORT_HTTP_ERROR
        if error.code in {
            "HCX_RESPONSE_DECODE_ERROR",
            "HCX_RESPONSE_JSON_ERROR",
            "HCX_RESPONSE_SHAPE_INVALID",
            "HCX_GENERATION_EMPTY",
        }:
            return GenerationValidationReason.TRANSPORT_RESPONSE_PARSE
        return GenerationValidationReason.TRANSPORT_CONNECTION_ERROR

    async def generate(self, generation_input: GenerationInput) -> GenerationResult:
        started_at = monotonic()
        prompt = build_evidence_only_prompt(generation_input)
        try:
            raw_output = await asyncio.wait_for(
                self._transport.generate(prompt.text),
                timeout=self._timeout_seconds,
            )
        except HCXTransportError as error:
            return self._fallback(
                generation_input,
                GenerationValidationStatus.TRANSPORT_ERROR,
                started_at,
                self._transport_reason(error),
                transport_error=error,
            )
        except Exception as error:
            return self._fallback(
                generation_input,
                GenerationValidationStatus.TRANSPORT_ERROR,
                started_at,
                GenerationValidationReason.TRANSPORT_EXCEPTION,
                unexpected_exception_class=type(error).__name__,
            )
        validation = self._validator.validate(generation_input, prompt, raw_output)
        if validation.accepted and validation.answer is not None:
            return GenerationResult(
                answer=validation.answer,
                provider="hyperclova_x",
                used_fallback=False,
                validation_status=validation.status,
                validation_reason=validation.reason,
                elapsed_ms=max(0.0, (monotonic() - started_at) * 1000),
            )
        if validation.status is not GenerationValidationStatus.REJECTED_FORMAT:
            return self._fallback(
                generation_input,
                validation.status,
                started_at,
                validation.reason,
            )
        repair_prompt = build_format_repair_prompt(
            prompt,
            raw_output,
            (
                validation.reason.value
                if validation.reason is not None
                else validation.status.value
            ),
        )
        if repair_prompt is None:
            return self._fallback(
                generation_input,
                validation.status,
                started_at,
                validation.reason,
            )
        try:
            repaired_output = await asyncio.wait_for(
                self._transport.generate(repair_prompt.text),
                timeout=self._timeout_seconds,
            )
        except HCXTransportError as error:
            return self._fallback(
                generation_input,
                GenerationValidationStatus.TRANSPORT_ERROR,
                started_at,
                self._transport_reason(error),
                transport_error=error,
            )
        except Exception as error:
            return self._fallback(
                generation_input,
                GenerationValidationStatus.TRANSPORT_ERROR,
                started_at,
                GenerationValidationReason.TRANSPORT_EXCEPTION,
                unexpected_exception_class=type(error).__name__,
            )
        repaired = self._validator.validate(
            generation_input,
            repair_prompt,
            repaired_output,
        )
        if not repaired.accepted or repaired.answer is None:
            return self._fallback(
                generation_input,
                repaired.status,
                started_at,
                repaired.reason,
            )
        return GenerationResult(
            answer=repaired.answer,
            provider="hyperclova_x",
            used_fallback=False,
            validation_status=repaired.status,
            validation_reason=GenerationValidationReason.FORMAT_REPAIR_ACCEPTED,
            elapsed_ms=max(0.0, (monotonic() - started_at) * 1000),
        )


__all__ = [
    "AnswerGenerator",
    "DeterministicAnswerGenerator",
    "HyperClovaAnswerGenerator",
]
