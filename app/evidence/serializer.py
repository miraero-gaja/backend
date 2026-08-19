"""Deterministic serialization of validated evidence for public context."""

import json

from app.core.constants import NO_EVIDENCE_CONTEXT
from app.evidence.models import SupportDecision, SupportStatus


def serialize_evidence(decision: SupportDecision) -> str:
    if decision.status is not SupportStatus.SUPPORTED or not decision.evidence:
        return NO_EVIDENCE_CONTEXT
    payload = [item.model_dump(mode="json") for item in decision.evidence]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

