"""Compile a closed query contract into inspectable parameterized PostgreSQL."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pipeline.normalize.models import TargetType

from .contracts import (
    AggregateFunction,
    FilterOperator,
    SemanticGateTrace,
    StructuredQueryContract,
    StructuredQueryStatus,
)
from .errors import StructuredQueryValidationError
from .registry import TrustedField, TrustedQueryRegistry, TrustedTable


_DECIMAL_LITERAL = re.compile(
    r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?", re.ASCII
)
_INTEGER_LITERAL = re.compile(r"[+-]?\d+", re.ASCII)
_DATE_LITERAL = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_TIMESTAMP_LITERAL = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", re.ASCII
)
_SQL_OPERATORS = {
    FilterOperator.EQ: "=",
    FilterOperator.NE: "<>",
    FilterOperator.LT: "<",
    FilterOperator.LE: "<=",
    FilterOperator.GT: ">",
    FilterOperator.GE: ">=",
}


def _quote(identifier: str) -> str:
    """Quote an identifier already validated by ``TrustedQueryRegistry``."""

    return f'"{identifier}"'


def _qualified_table(table: TrustedTable) -> str:
    return f"{_quote(table.schema_name)}.{_quote(table.table_name)}"


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise StructuredQueryValidationError("boolean is not a DECIMAL value")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise StructuredQueryValidationError("DECIMAL value must be finite")
        result = Decimal(str(value))
    elif isinstance(value, str) and _DECIMAL_LITERAL.fullmatch(value):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - regex is stricter
            raise StructuredQueryValidationError("malformed DECIMAL value") from exc
    else:
        raise StructuredQueryValidationError("malformed DECIMAL value")
    if not result.is_finite():
        raise StructuredQueryValidationError("DECIMAL value must be finite")
    return result


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise StructuredQueryValidationError("boolean is not an INTEGER value")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        return int(value)
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str) and _INTEGER_LITERAL.fullmatch(value):
        return int(value)
    raise StructuredQueryValidationError("malformed INTEGER value")


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        raise StructuredQueryValidationError("datetime is not a DATE value")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE_LITERAL.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise StructuredQueryValidationError("malformed DATE value") from exc
    raise StructuredQueryValidationError("malformed DATE value")


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise StructuredQueryValidationError(
                "timezone-aware value is not valid for the official naive TIMESTAMP fields"
            )
        return value
    if isinstance(value, str) and _TIMESTAMP_LITERAL.fullmatch(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise StructuredQueryValidationError("malformed TIMESTAMP value") from exc
    raise StructuredQueryValidationError("malformed TIMESTAMP value")


def _coerce_bound_value(field: TrustedField, value: Any) -> Any:
    if field.target_type is TargetType.TEXT:
        if not isinstance(value, str):
            raise StructuredQueryValidationError(
                f"{field.semantic_key} requires a TEXT value"
            )
        if field.is_null_equivalent(value):
            raise StructuredQueryValidationError(
                f"{field.semantic_key} null-equivalent source literal is not "
                "an actual query value"
            )
        return value
    if field.target_type is TargetType.DECIMAL:
        return _decimal(value)
    if field.target_type is TargetType.INTEGER:
        return _integer(value)
    if field.target_type is TargetType.DATE:
        return _date(value)
    if field.target_type is TargetType.TIMESTAMP:
        return _timestamp(value)
    raise StructuredQueryValidationError(
        f"{field.semantic_key} has unsupported target type {field.target_type.value}"
    )


@dataclass(frozen=True, slots=True)
class SelectedField:
    field: TrustedField
    value_alias: str
    condition_id: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledStructuredQuery:
    """SQL plus binding/evidence metadata produced without touching a DB."""

    sql: str
    parameters: tuple[Any, ...]
    table: TrustedTable
    projected_fields: tuple[SelectedField, ...]
    evidence_fields: tuple[SelectedField, ...]
    aggregate: AggregateFunction | None
    planning_status: StructuredQueryStatus = StructuredQueryStatus.SUPPORTED
    semantic_gate_trace: tuple[SemanticGateTrace, ...] = ()

    @property
    def is_count(self) -> bool:
        return self.aggregate is AggregateFunction.COUNT


class StructuredQueryCompiler:
    def __init__(self, registry: TrustedQueryRegistry) -> None:
        self._registry = registry

    def _known_field(
        self,
        product_scope: str,
        semantic_key: str,
    ) -> TrustedField:
        field = self._registry.field(product_scope, semantic_key)
        if field is None:
            raise StructuredQueryValidationError(
                f"unknown or unconfirmed field: {product_scope}.{semantic_key}"
            )
        return field

    def _field(
        self,
        product_scope: str,
        semantic_key: str,
        operation: str,
    ) -> TrustedField:
        field = self._known_field(product_scope, semantic_key)
        if operation not in field.allowed_operations:
            raise StructuredQueryValidationError(
                f"operator {operation} is not allowed for "
                f"{product_scope}.{semantic_key}"
            )
        return field

    def compile(self, query: StructuredQueryContract) -> CompiledStructuredQuery:
        table = self._registry.table(query.product_scope)
        if table is None:
            raise StructuredQueryValidationError(
                f"unknown product scope: {query.product_scope}"
            )

        parameters: list[Any] = []
        predicates: list[str] = []
        filter_fields: list[tuple[TrustedField, str]] = []
        for index, clause in enumerate(query.filters, start=1):
            field = self._field(
                query.product_scope, clause.field, clause.operator.value
            )
            bound_value = _coerce_bound_value(field, clause.value)
            predicates.append(
                f"{_quote(field.physical_column)} "
                f"{_SQL_OPERATORS[clause.operator]} %s"
            )
            parameters.append(bound_value)
            filter_fields.append((field, f"filter_{index}"))

        if query.aggregate is AggregateFunction.COUNT:
            select_sql = 'COUNT(*) AS "__count"'
            projected: tuple[SelectedField, ...] = ()
            evidence: tuple[SelectedField, ...] = ()
        else:
            # Projection is permitted by CONFIRMED membership itself.  It must
            # not borrow a comparison permission: some official metrics are
            # deliberately exposed for source-native SORT only.
            projection_fields = tuple(
                self._known_field(query.product_scope, name)
                for name in query.projections
            )
            all_evidence_fields: list[tuple[TrustedField, str | None]] = [
                (field, None) for field in projection_fields
            ]
            all_evidence_fields.extend(filter_fields)
            if query.sort is not None:
                sort_field = self._field(
                    query.product_scope, query.sort.field, "SORT"
                )
                all_evidence_fields.append((sort_field, None))

            deduplicated: list[tuple[TrustedField, str | None]] = []
            seen: dict[str, int] = {}
            for field, condition_id in all_evidence_fields:
                position = seen.get(field.semantic_key)
                if position is None:
                    seen[field.semantic_key] = len(deduplicated)
                    deduplicated.append((field, condition_id))
                elif deduplicated[position][1] is None and condition_id is not None:
                    deduplicated[position] = (field, condition_id)

            evidence = tuple(
                SelectedField(field, f"__value_{index:03d}", condition_id)
                for index, (field, condition_id) in enumerate(deduplicated)
            )
            by_key = {selection.field.semantic_key: selection for selection in evidence}
            projected = tuple(by_key[field.semantic_key] for field in projection_fields)
            technical_selects = [
                f'{_quote(table.source_row_id_column)} AS "__source_row_id"',
                f'{_quote(table.logical_table_id_column)} AS "__logical_table_id"',
                f'{_quote(table.raw_record_column)} AS "__raw_record"',
                f'{_quote(table.parse_statuses_column)} AS "__parse_statuses"',
            ]
            value_selects = [
                f'{_quote(selection.field.physical_column)} '
                f'AS {_quote(selection.value_alias)}'
                for selection in evidence
            ]
            select_sql = ", ".join(technical_selects + value_selects)

        availability_fields = (
            tuple(field for field, _ in filter_fields)
            if query.aggregate is AggregateFunction.COUNT
            else tuple(selection.field for selection in evidence)
        )
        guarded_keys: set[str] = set()
        for field in availability_fields:
            if (
                not field.null_equivalent_literals
                or field.semantic_key in guarded_keys
            ):
                continue
            guarded_keys.add(field.semantic_key)
            placeholders = ", ".join(
                "%s" for _ in field.null_equivalent_literals
            )
            physical_column = _quote(field.physical_column)
            predicates.append(
                f"({physical_column} IS NOT NULL AND "
                f"{physical_column} NOT IN ({placeholders}))"
            )
            parameters.extend(field.null_equivalent_literals)

        sql_parts = [
            f"SELECT {select_sql}",
            f"FROM {_qualified_table(table)}",
        ]
        if predicates:
            sql_parts.append("WHERE " + " AND ".join(predicates))
        if query.aggregate is not AggregateFunction.COUNT:
            if query.sort is not None:
                sort_field = self._field(query.product_scope, query.sort.field, "SORT")
                sql_parts.append(
                    f"ORDER BY {_quote(sort_field.physical_column)} "
                    f"{query.sort.direction.value} NULLS LAST, "
                    f"{_quote(table.source_row_id_column)} ASC"
                )
            else:
                sql_parts.append(
                    f"ORDER BY {_quote(table.source_row_id_column)} ASC"
                )
            if query.limit is not None:
                sql_parts.append("LIMIT %s")
                parameters.append(query.limit)

        return CompiledStructuredQuery(
            sql="\n".join(sql_parts),
            parameters=tuple(parameters),
            table=table,
            projected_fields=projected,
            evidence_fields=evidence,
            aggregate=query.aggregate,
        )


__all__ = [
    "CompiledStructuredQuery",
    "SelectedField",
    "StructuredQueryCompiler",
]
