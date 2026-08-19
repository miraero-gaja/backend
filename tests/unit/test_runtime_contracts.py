"""Shape checks for the typed runtime contracts.

These tests intentionally verify contract plumbing only; they do not invent any
financial product fields before schema profiling is available.
"""

from pydantic import BaseModel

from app.agent.contracts import QueryContract, ToolResult
from app.evidence.models import (
    EvidenceItem,
    ReasonCode,
    SupportDecision,
    SupportStatus,
)


def test_query_contract_exposes_required_runtime_fields() -> None:
    expected_fields = {
        "request_id",
        "question_id",
        "product_scopes",
        "filters",
        "projections",
        "sort",
        "limit",
        "semantic_intent",
        "ambiguity",
        "required_inputs",
        "route_hint",
    }

    assert set(QueryContract.model_fields) == expected_fields


def test_tool_result_exposes_required_runtime_fields() -> None:
    expected_fields = {
        "tool_name",
        "query_fingerprint",
        "candidates",
        "columns",
        "elapsed_ms",
        "warnings",
        "error_code",
    }

    assert set(ToolResult.model_fields) == expected_fields


def test_evidence_item_stays_source_and_rule_traceable() -> None:
    expected_fields = {
        "product_key",
        "source_table",
        "source_row_id",
        "source_field",
        "raw_value",
        "normalized_value",
        "unit",
        "condition_id",
        "decision",
        "formula_id",
        "ruleset_version",
    }

    assert set(EvidenceItem.model_fields) == expected_fields | {
        "snapshot",
        "effective_date",
    }


def test_support_status_values_match_the_runtime_contract() -> None:
    assert {status.value for status in SupportStatus} == {
        "SUPPORTED",
        "PARTIAL",
        "UNSUPPORTED",
        "NO_MATCH",
    }


def test_reason_code_values_match_the_runtime_contract() -> None:
    assert {reason.value for reason in ReasonCode} == {
        "FIELD_NOT_AVAILABLE",
        "MISSING_REQUIRED_INPUT",
        "NO_MATCH",
        "OUT_OF_SCOPE",
        "UNKNOWN_ENTITY",
        "SOURCE_CONFLICT",
        "TOOL_FAILURE",
    }


def test_support_decision_is_a_typed_model_with_status() -> None:
    assert issubclass(SupportDecision, BaseModel)
    assert set(SupportDecision.model_fields) == {
        "status",
        "reason_codes",
        "evidence",
        "summary",
    }
