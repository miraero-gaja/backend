"""Opt-in, single-request live HyperCLOVA X smoke test."""

from __future__ import annotations

import asyncio
import os

import pytest

from app.core.config import Settings
from app.evidence.models import EvidenceItem, SupportStatus
from app.generation import GenerationInput, HyperClovaAnswerGenerator
from app.llm import build_hcx_client


HCX_ENABLED = os.getenv("HCX_ENABLED", "").lower() in {"1", "true", "yes"}
HCX_API_KEY_SET = bool(os.getenv("HCX_API_KEY"))
HCX_API_URL_SET = bool(os.getenv("HCX_API_URL"))


@pytest.mark.skipif(
    not (HCX_ENABLED and HCX_API_KEY_SET and HCX_API_URL_SET),
    reason="HCX_ENABLED/HCX_API_KEY/HCX_API_URL are not configured",
)
def test_live_hcx_evidence_only_smoke() -> None:
    settings = Settings(_env_file=None)
    evidence = EvidenceItem(
        product_key="smoke-product",
        source_table="PREF02N001",
        source_row_id="srid:v1:hcx-smoke",
        source_field="pd_nm#1",
        raw_value="검증 상품",
        normalized_value="검증 상품",
        decision=SupportStatus.SUPPORTED,
    )
    generation_input = GenerationInput(
        question="검증된 상품명을 간결하게 알려주세요.",
        support_status=SupportStatus.SUPPORTED,
        evidence=(evidence,),
        execution_trace="Evidence fixture 검증",
        deterministic_fallback_answer="검증 상품을 확인했습니다.",
    )

    result = asyncio.run(
        HyperClovaAnswerGenerator(build_hcx_client(settings)).generate(
            generation_input
        )
    )

    assert result.provider == "hyperclova_x"
    assert isinstance(result.used_fallback, bool)
    assert result.answer
    assert result.elapsed_ms >= 0
