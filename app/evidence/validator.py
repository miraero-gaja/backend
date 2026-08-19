"""Evidence gating that makes unsupported the default, never an inferred answer."""

from collections.abc import Iterable

from app.agent.contracts import QueryContract, ToolResult
from app.evidence.models import EvidenceItem, ReasonCode, SupportDecision, SupportStatus


class EvidenceValidator:
    """Decide support solely from source-addressable evidence and tool outcomes."""

    def validate(
        self,
        query: QueryContract,
        tool_results: Iterable[ToolResult],
        evidence: Iterable[EvidenceItem] = (),
    ) -> SupportDecision:
        items = tuple(evidence)
        results = tuple(tool_results)
        if query.required_inputs:
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.MISSING_REQUIRED_INPUT,),
                evidence=items,
                summary="required_request_input_missing",
            )
        if not items:
            result_codes = tuple(
                result.error_code for result in results if result.error_code is not None
            )
            if ReasonCode.NO_MATCH in result_codes:
                return SupportDecision(
                    status=SupportStatus.NO_MATCH,
                    reason_codes=(ReasonCode.NO_MATCH,),
                    summary="retrieval_returned_no_match",
                )
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(
                    tuple(dict.fromkeys(result_codes)) or (ReasonCode.TOOL_FAILURE,)
                ),
                summary="no_validated_evidence",
            )
        statuses = {item.decision for item in items}
        if statuses == {SupportStatus.SUPPORTED}:
            return SupportDecision(
                status=SupportStatus.SUPPORTED,
                evidence=items,
                summary="all_evidence_supported",
            )
        if SupportStatus.SUPPORTED in statuses or SupportStatus.PARTIAL in statuses:
            return SupportDecision(
                status=SupportStatus.PARTIAL,
                reason_codes=(ReasonCode.FIELD_NOT_AVAILABLE,),
                evidence=items,
                summary="evidence_only_partially_supports_answer",
            )
        if statuses == {SupportStatus.NO_MATCH}:
            return SupportDecision(
                status=SupportStatus.NO_MATCH,
                reason_codes=(ReasonCode.NO_MATCH,),
                evidence=items,
                summary="evidence_items_report_no_match",
            )
        return SupportDecision(
            status=SupportStatus.UNSUPPORTED,
            reason_codes=(ReasonCode.OUT_OF_SCOPE,),
            evidence=items,
            summary="evidence_does_not_support_answer",
        )
