"""Convert typed staging rows into source-addressable EvidenceItems."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.evidence.models import EvidenceItem, ScalarValue, SupportStatus
from pipeline.normalize.models import ParseStatus

from .compiler import CompiledStructuredQuery
from .errors import StructuredQueryValidationError


def json_safe_scalar(value: Any) -> ScalarValue:
    """Preserve exact decimals as text and dates as ISO values for contracts."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise StructuredQueryValidationError(
        f"database returned unsupported scalar type: {type(value)!r}"
    )


def _raw_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StructuredQueryValidationError(
                "database raw_record is not valid JSON"
            ) from exc
    if not isinstance(value, Mapping):
        raise StructuredQueryValidationError("database raw_record must be an object")
    return value


def _parse_status_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StructuredQueryValidationError(
                "database parse_statuses is not valid JSON"
            ) from exc
    if not isinstance(value, Mapping):
        raise StructuredQueryValidationError(
            "database parse_statuses must be an object"
        )
    return value


def _decode_raw(envelope: Any) -> ScalarValue:
    if not isinstance(envelope, Mapping):
        raise StructuredQueryValidationError("raw field envelope must be an object")
    kind = envelope.get("type")
    value = envelope.get("value")
    if kind == "NULL":
        return None
    if kind == "BOOLEAN":
        if value == "true":
            return True
        if value == "false":
            return False
        raise StructuredQueryValidationError("invalid raw BOOLEAN envelope")
    if kind == "STRING":
        if not isinstance(value, str):
            raise StructuredQueryValidationError("invalid raw STRING envelope")
        return value
    if kind == "INTEGER":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise StructuredQueryValidationError("invalid raw INTEGER envelope") from exc
    if kind == "FLOAT":
        try:
            return float.fromhex(value)
        except (TypeError, ValueError) as exc:
            raise StructuredQueryValidationError("invalid raw FLOAT envelope") from exc
    if kind in {"DECIMAL", "DATE", "DATETIME", "TIME"}:
        if not isinstance(value, str):
            raise StructuredQueryValidationError(f"invalid raw {kind} envelope")
        return value
    raise StructuredQueryValidationError(f"unknown raw envelope type: {kind!r}")


def row_to_candidate(
    row: Mapping[str, Any],
    compiled: CompiledStructuredQuery,
) -> dict[str, ScalarValue]:
    return {
        selection.field.semantic_key: json_safe_scalar(row[selection.value_alias])
        for selection in compiled.projected_fields
    }


def row_to_evidence(
    row: Mapping[str, Any],
    compiled: CompiledStructuredQuery,
) -> tuple[EvidenceItem, ...]:
    source_row_id = row.get("__source_row_id")
    source_table = row.get("__logical_table_id")
    if not isinstance(source_row_id, str) or not source_row_id:
        raise StructuredQueryValidationError("result row is missing source_row_id")
    if source_table != compiled.table.logical_table_id:
        raise StructuredQueryValidationError("result row logical table mismatch")
    raw_record = _raw_mapping(row.get("__raw_record"))
    parse_statuses = _parse_status_mapping(row.get("__parse_statuses"))

    evidence: list[EvidenceItem] = []
    for selection in compiled.evidence_fields:
        qualified_name = selection.field.qualified_name
        if qualified_name not in raw_record:
            raise StructuredQueryValidationError(
                f"raw_record is missing {qualified_name}"
            )
        if selection.value_alias not in row:
            raise StructuredQueryValidationError(
                f"result row is missing {selection.value_alias}"
            )
        parse_status = parse_statuses.get(qualified_name)
        if not isinstance(parse_status, str):
            raise StructuredQueryValidationError(
                f"parse_statuses is missing {qualified_name}"
            )
        try:
            parsed_status = ParseStatus(parse_status)
        except ValueError as exc:
            raise StructuredQueryValidationError(
                f"parse_statuses contains an unknown status for {qualified_name}"
            ) from exc
        evidence.append(
            EvidenceItem(
                # No inferred business key: the immutable technical lineage key
                # is used until a product identifier is explicitly approved.
                product_key=source_row_id,
                source_table=source_table,
                source_row_id=source_row_id,
                source_field=selection.field.qualified_name,
                raw_value=_decode_raw(raw_record[qualified_name]),
                normalized_value=json_safe_scalar(row[selection.value_alias]),
                unit=selection.field.unit,
                condition_id=selection.condition_id,
                # Only successfully parsed values may support an answer.
                # MISSING/EMPTY/WHITESPACE_ONLY/PARSE_ERROR/NOT_APPLICABLE
                # remain visible in raw lineage but fail the evidence gate.
                decision=(
                    SupportStatus.SUPPORTED
                    if parsed_status is ParseStatus.OK
                    else SupportStatus.UNSUPPORTED
                ),
            )
        )
    return tuple(evidence)


__all__ = ["json_safe_scalar", "row_to_candidate", "row_to_evidence"]
