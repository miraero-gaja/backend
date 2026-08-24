"""Deterministic evidence validation before facts reach answer generation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agent.contracts import (
    QueryContract,
    QueryUnderstandingStatus,
    RouteHint,
    ToolResult,
)
from app.evidence.models import EvidenceItem, ReasonCode, SupportDecision, SupportStatus
from app.structured.contracts import (
    FilterOperator,
    SortDirection,
    StructuredQueryContract,
    StructuredQueryStatus,
)
from app.structured.executor import (
    StructuredExecutionResult,
    structured_query_fingerprint,
)
from mappings.semantic import (
    get_product_identifier_key,
    get_semantic_field_approval,
)
from pipeline.normalize.models import TargetType


class StructuredEvidenceValidationError(ValueError):
    """Raised when returned structured rows violate their approved contract."""


def _typed_value(target_type: TargetType, value: Any) -> Any:
    if value is None:
        return None
    if target_type is TargetType.TEXT:
        if not isinstance(value, str):
            raise StructuredEvidenceValidationError("TEXT evidence is not a string")
        return value
    if target_type is TargetType.DECIMAL:
        if isinstance(value, bool):
            raise StructuredEvidenceValidationError("DECIMAL evidence is boolean")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise StructuredEvidenceValidationError(
                "DECIMAL evidence is malformed"
            ) from error
        if not parsed.is_finite():
            raise StructuredEvidenceValidationError(
                "DECIMAL evidence must be finite"
            )
        return parsed
    if target_type is TargetType.INTEGER:
        if isinstance(value, bool):
            raise StructuredEvidenceValidationError("INTEGER evidence is boolean")
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise StructuredEvidenceValidationError(
                "INTEGER evidence is malformed"
            ) from error
    if target_type is TargetType.DATE:
        if isinstance(value, datetime):
            raise StructuredEvidenceValidationError("DATE evidence is a datetime")
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as error:
            raise StructuredEvidenceValidationError(
                "DATE evidence is malformed"
            ) from error
    if target_type is TargetType.TIMESTAMP:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError as error:
            raise StructuredEvidenceValidationError(
                "TIMESTAMP evidence is malformed"
            ) from error
    raise StructuredEvidenceValidationError("unsupported evidence target type")


def _comparison_holds(left: Any, operator: FilterOperator, right: Any) -> bool:
    if left is None:
        return False
    if operator is FilterOperator.EQ:
        return left == right
    if operator is FilterOperator.NE:
        return left != right
    if operator is FilterOperator.LT:
        return left < right
    if operator is FilterOperator.LE:
        return left <= right
    if operator is FilterOperator.GT:
        return left > right
    if operator is FilterOperator.GE:
        return left >= right
    return False


def _requested_semantic_keys(
    query: StructuredQueryContract,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *query.projections,
                *(clause.field for clause in query.filters),
                *((query.sort.field,) if query.sort is not None else ()),
            )
        )
    )


class StructuredEvidenceValidator:
    """Validate compiled structured results without inferring financial meaning."""

    def validate(
        self,
        query: StructuredQueryContract,
        result: StructuredExecutionResult,
    ) -> tuple[str, ...]:
        compiled = result.compiled_query
        trace = [f"상품군 확인: {query.product_scope}"]
        if result.query_fingerprint != structured_query_fingerprint(query):
            raise StructuredEvidenceValidationError("query fingerprint mismatch")
        if compiled.table.logical_table_id != query.product_scope:
            raise StructuredEvidenceValidationError("compiled table mismatch")
        if compiled.aggregate is not query.aggregate:
            raise StructuredEvidenceValidationError("compiled aggregate mismatch")
        if result.status not in {
            StructuredQueryStatus.SUPPORTED,
            StructuredQueryStatus.RESOLVED_WITH_ASSUMPTION,
            StructuredQueryStatus.NO_MATCH,
        }:
            raise StructuredEvidenceValidationError("structured plan was not approved")

        g3_keys = tuple(
            key
            for key in _requested_semantic_keys(query)
            if get_semantic_field_approval(query.product_scope, key) is not None
        )
        if g3_keys:
            if not result.semantic_gate_trace or any(
                item.status is StructuredQueryStatus.UNSUPPORTED
                for item in result.semantic_gate_trace
            ):
                raise StructuredEvidenceValidationError(
                    "semantic gate approval trace is missing or blocked"
                )
            for semantic_key in g3_keys:
                if not any(
                    item.semantic_key == semantic_key
                    and item.status is StructuredQueryStatus.SUPPORTED
                    for item in result.semantic_gate_trace
                ):
                    raise StructuredEvidenceValidationError(
                        "semantic key approval trace is missing"
                    )
            required_operations = (
                *((semantic_key, "PROJECT") for semantic_key in query.projections),
                *(
                    (clause.field, clause.operator.value)
                    for clause in query.filters
                    if clause.field in g3_keys
                ),
                *(
                    ((query.sort.field, f"SORT_{query.sort.direction.value}"),)
                    if query.sort is not None and query.sort.field in g3_keys
                    else ()
                ),
            )
            for semantic_key, operation in required_operations:
                if not any(
                    item.semantic_key == semantic_key
                    and item.operation == operation
                    and item.status is StructuredQueryStatus.SUPPORTED
                    for item in result.semantic_gate_trace
                ):
                    raise StructuredEvidenceValidationError(
                        "semantic operation approval trace is missing"
                    )
            trace.append("semantic gate 승인 확인")

        trace.append("Structured 실행 성공")
        if result.status is StructuredQueryStatus.NO_MATCH:
            if result.candidates or result.evidence:
                raise StructuredEvidenceValidationError(
                    "NO_MATCH result contains rows or evidence"
                )
            trace.extend(("0건 반환", "NO_MATCH 확정"))
            return tuple(trace)

        if compiled.is_count:
            if len(result.candidates) != 1 or result.evidence:
                raise StructuredEvidenceValidationError(
                    "COUNT result shape or evidence is invalid"
                )
            trace.append("COUNT 결과 형식 확인")
            return tuple(trace)

        if not result.candidates:
            raise StructuredEvidenceValidationError(
                "successful row query has no candidates"
            )
        if query.limit is not None and len(result.candidates) > query.limit:
            raise StructuredEvidenceValidationError("result exceeds Top-N limit")
        if result.columns != query.projections:
            raise StructuredEvidenceValidationError("result columns mismatch")

        expected_fields = {
            selection.field.qualified_name
            for selection in compiled.evidence_fields
        }
        row_order: list[str] = []
        by_row: dict[str, dict[str, EvidenceItem]] = {}
        for item in result.evidence:
            if not item.source_row_id or not item.product_key:
                raise StructuredEvidenceValidationError(
                    "source row identity is missing"
                )
            if item.source_table != query.product_scope:
                raise StructuredEvidenceValidationError(
                    "evidence logical table mismatch"
                )
            if item.source_row_id not in by_row:
                row_order.append(item.source_row_id)
                by_row[item.source_row_id] = {}
            row_fields = by_row[item.source_row_id]
            if item.source_field in row_fields:
                raise StructuredEvidenceValidationError(
                    "duplicate source field evidence"
                )
            row_fields[item.source_field] = item

        if len(row_order) != len(result.candidates):
            raise StructuredEvidenceValidationError(
                "candidate and source row counts differ"
            )
        for row_fields in by_row.values():
            if set(row_fields) != expected_fields:
                raise StructuredEvidenceValidationError(
                    "row evidence fields are incomplete"
                )

        identifier_key = get_product_identifier_key(query.product_scope)
        identifier_selection = next(
            (
                selection
                for selection in compiled.projected_fields
                if selection.field.semantic_key == identifier_key
            ),
            None,
        )
        for row_id, row_fields in by_row.items():
            expected_product_key = row_id
            if identifier_selection is not None:
                identifier_item = row_fields[
                    identifier_selection.field.qualified_name
                ]
                identifier_value = identifier_item.normalized_value
                if (
                    identifier_item.decision is not SupportStatus.SUPPORTED
                    or not isinstance(identifier_value, str)
                    or not identifier_value.strip()
                ):
                    raise StructuredEvidenceValidationError(
                        "approved product identifier evidence is missing"
                    )
                expected_product_key = identifier_value
            if any(
                item.product_key != expected_product_key
                for item in row_fields.values()
            ):
                raise StructuredEvidenceValidationError(
                    "product identifier provenance conflicts within the row"
                )

        selections = {
            selection.field.semantic_key: selection
            for selection in compiled.evidence_fields
        }
        for index, candidate in enumerate(result.candidates):
            row_fields = by_row[row_order[index]]
            if set(candidate) != set(query.projections):
                raise StructuredEvidenceValidationError(
                    "candidate projection shape mismatch"
                )
            for selection in compiled.projected_fields:
                semantic_key = selection.field.semantic_key
                if semantic_key not in candidate:
                    raise StructuredEvidenceValidationError(
                        "candidate projection is missing"
                    )
                item = row_fields[selection.field.qualified_name]
                if candidate[semantic_key] != item.normalized_value:
                    raise StructuredEvidenceValidationError(
                        "candidate and evidence values differ"
                    )
                if (
                    selection.field.target_type is TargetType.TEXT
                    and item.raw_value != item.normalized_value
                ):
                    raise StructuredEvidenceValidationError(
                        "projected text differs from its raw source value"
                    )

        for filter_index, clause in enumerate(query.filters, start=1):
            selection = selections[clause.field]
            expected = _typed_value(selection.field.target_type, clause.value)
            for row_fields in by_row.values():
                item = row_fields[selection.field.qualified_name]
                if item.decision is not SupportStatus.SUPPORTED:
                    raise StructuredEvidenceValidationError(
                        "filter evidence is not supported"
                    )
                if (
                    selection.condition_id is None
                    or item.condition_id != selection.condition_id
                ):
                    raise StructuredEvidenceValidationError(
                        f"filter_{filter_index} condition identity is missing"
                    )
                actual = _typed_value(
                    selection.field.target_type,
                    item.normalized_value,
                )
                if not _comparison_holds(actual, clause.operator, expected):
                    raise StructuredEvidenceValidationError(
                        "returned value violates a query filter"
                    )
        if query.filters:
            trace.append(f"필터 {len(query.filters)}개 검증")

        if query.sort is not None:
            selection = selections[query.sort.field]
            ordered: list[tuple[Any, str]] = []
            for row_id in row_order:
                item = by_row[row_id][selection.field.qualified_name]
                if item.decision is not SupportStatus.SUPPORTED:
                    raise StructuredEvidenceValidationError(
                        "sort evidence is not supported"
                    )
                ordered.append(
                    (
                        _typed_value(
                            selection.field.target_type,
                            item.normalized_value,
                        ),
                        row_id,
                    )
                )
            for previous, current in zip(ordered, ordered[1:]):
                previous_value, previous_id = previous
                current_value, current_id = current
                if previous_value is None and current_value is not None:
                    raise StructuredEvidenceValidationError(
                        "NULL sort ordering is invalid"
                    )
                if previous_value is not None and current_value is not None:
                    wrong_direction = (
                        previous_value < current_value
                        if query.sort.direction is SortDirection.DESC
                        else previous_value > current_value
                    )
                    if wrong_direction:
                        raise StructuredEvidenceValidationError(
                            "returned rows violate sort direction"
                        )
                if previous_value == current_value and previous_id > current_id:
                    raise StructuredEvidenceValidationError(
                        "source row tie-break ordering is invalid"
                    )
            trace.append(f"정렬 검증: {query.sort.direction.value}")

        trace.append(f"{len(result.candidates)}건 반환")
        if query.limit is not None:
            trace.append(f"Top-N 검증: {query.limit}")
        trace.append("Evidence 확정")
        return tuple(trace)


def _trace_summary(results: tuple[ToolResult, ...], fallback: str) -> str:
    trace = tuple(
        step for result in results for step in result.validation_trace
    )
    return " → ".join(trace) if trace else fallback


class EvidenceValidator:
    """Create a fail-closed decision from validated tool outcomes."""

    def validate(
        self,
        query: QueryContract,
        tool_results: Iterable[ToolResult],
        evidence: Iterable[EvidenceItem] = (),
    ) -> SupportDecision:
        results = tuple(tool_results)
        supplied_items = tuple(evidence)
        result_items = tuple(item for result in results for item in result.evidence)
        items = result_items or supplied_items

        if query.required_inputs:
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.MISSING_REQUIRED_INPUT,),
                evidence=(),
                summary="필수 입력 확인 실패 → UNSUPPORTED",
            )
        if query.understanding is not None and query.understanding.status in {
            QueryUnderstandingStatus.AMBIGUOUS,
            QueryUnderstandingStatus.UNSUPPORTED,
        }:
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.FIELD_NOT_AVAILABLE,),
                evidence=(),
                summary="semantic 승인 실패 → UNSUPPORTED",
            )
        if supplied_items and result_items and supplied_items != result_items:
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.SOURCE_CONFLICT,),
                summary="tool evidence 불일치 → UNSUPPORTED",
            )

        result_codes = tuple(
            result.error_code for result in results if result.error_code is not None
        )
        failure_codes = tuple(
            dict.fromkeys(
                code for code in result_codes if code is not ReasonCode.NO_MATCH
            )
        )
        if failure_codes:
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=failure_codes,
                summary="Structured 실행 실패 → TOOL_FAILURE",
            )
        if ReasonCode.NO_MATCH in result_codes:
            if items or any(result.candidates for result in results):
                return SupportDecision(
                    status=SupportStatus.UNSUPPORTED,
                    reason_codes=(ReasonCode.SOURCE_CONFLICT,),
                    summary="NO_MATCH 결과 충돌 → UNSUPPORTED",
                )
            return SupportDecision(
                status=SupportStatus.NO_MATCH,
                reason_codes=(ReasonCode.NO_MATCH,),
                summary=_trace_summary(results, "정상 실행 → 0건 반환 → NO_MATCH"),
            )
        if not items:
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.TOOL_FAILURE,),
                summary="검증 가능한 row evidence 없음 → UNSUPPORTED",
            )
        if query.route_hint is RouteHint.STRUCTURED and any(
            result.tool_name == "structured" and not result.validation_trace
            for result in results
        ):
            return SupportDecision(
                status=SupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.SOURCE_CONFLICT,),
                summary="structured validation trace 누락 → UNSUPPORTED",
            )

        statuses = {item.decision for item in items}
        if statuses == {SupportStatus.SUPPORTED}:
            return SupportDecision(
                status=SupportStatus.SUPPORTED,
                evidence=items,
                summary=_trace_summary(results, "Evidence 확정 → SUPPORTED"),
            )
        if SupportStatus.SUPPORTED in statuses or SupportStatus.PARTIAL in statuses:
            return SupportDecision(
                status=SupportStatus.PARTIAL,
                reason_codes=(ReasonCode.FIELD_NOT_AVAILABLE,),
                evidence=items,
                summary=_trace_summary(results, "일부 evidence 검증 → PARTIAL"),
            )
        return SupportDecision(
            status=SupportStatus.UNSUPPORTED,
            reason_codes=(ReasonCode.FIELD_NOT_AVAILABLE,),
            evidence=items,
            summary="요청 evidence 검증 실패 → UNSUPPORTED",
        )


__all__ = [
    "EvidenceValidator",
    "StructuredEvidenceValidationError",
    "StructuredEvidenceValidator",
]
