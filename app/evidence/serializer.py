"""Bounded deterministic serialization of public evidence context."""

from __future__ import annotations

import json
from typing import Any

from app.core.constants import NO_EVIDENCE_CONTEXT
from app.evidence.models import ReasonCode, SupportDecision, SupportStatus


MAX_RETRIEVED_CONTEXT_CHARS = 6000
MAX_PUBLIC_EVIDENCE_ITEMS = 20


def _compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _public_item(item) -> dict[str, Any]:
    record: dict[str, Any] = {
        "condition_id": item.condition_id,
        "decision": item.decision.value,
        "normalized_value": item.normalized_value,
        "product_key": item.product_key,
        "raw_value": item.raw_value,
        "source_field": item.source_field,
        "source_row_id": item.source_row_id,
        "source_table": item.source_table,
    }
    for name in ("unit", "snapshot", "effective_date"):
        value = getattr(item, name)
        if value is not None:
            record[name] = value.isoformat() if hasattr(value, "isoformat") else value
    return record


def _evidence_payload(decision: SupportDecision) -> str:
    approved = tuple(
        item
        for item in decision.evidence
        if item.decision is SupportStatus.SUPPORTED
    )
    payload: dict[str, Any] = {
        "aggregate_evidence": [
            {
                "condition_ids": list(item.condition_ids),
                "decision": item.decision.value,
                "operation": item.operation,
                "source_table": item.source_table,
                "value": item.value,
            }
            for item in decision.aggregate_evidence
            if item.decision is SupportStatus.SUPPORTED
        ],
        "evidence": [],
        "evidence_count": len(approved),
        "row_count": len({item.source_row_id for item in approved}),
        "status": decision.status.value,
    }
    for item in approved[:MAX_PUBLIC_EVIDENCE_ITEMS]:
        trial = dict(payload)
        trial["evidence"] = [*payload["evidence"], _public_item(item)]
        trial["truncated"] = len(trial["evidence"]) < len(approved)
        encoded = _compact_json(trial)
        if len(encoded) > MAX_RETRIEVED_CONTEXT_CHARS:
            break
        payload = trial
    payload["truncated"] = len(payload["evidence"]) < len(approved)
    return _compact_json(payload)


def serialize_evidence(
    decision: SupportDecision,
    *,
    unsupported_reason: str | None = None,
) -> str:
    if decision.status in {SupportStatus.SUPPORTED, SupportStatus.PARTIAL}:
        return _evidence_payload(decision)
    if decision.status is SupportStatus.NO_MATCH:
        return _compact_json(
            {"reason": "normal_execution_zero_rows", "status": "NO_MATCH"}
        )
    if ReasonCode.TOOL_FAILURE in decision.reason_codes:
        return _compact_json(
            {"reason": "structured_retrieval_failed", "status": "TOOL_FAILURE"}
        )
    if unsupported_reason and unsupported_reason not in {
        "product_scope_missing",
        "multiple_product_scopes",
    }:
        return _compact_json(
            {"reason": unsupported_reason, "status": "UNSUPPORTED"}
        )
    return NO_EVIDENCE_CONTEXT


__all__ = [
    "MAX_PUBLIC_EVIDENCE_ITEMS",
    "MAX_RETRIEVED_CONTEXT_CHARS",
    "serialize_evidence",
]
