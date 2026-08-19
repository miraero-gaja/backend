"""Trusted SQL identifiers and Priority-A field capabilities.

User-provided semantic field names are lookup keys only.  Every identifier that
can enter compiled SQL is supplied by this registry and validated when the
registry is constructed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pipeline.normalize.models import TargetType

from .contracts import FilterOperator
from .errors import StructuredRegistryError


_SQL_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*", re.ASCII)
_COMPARISONS = frozenset(operator.value for operator in FilterOperator)
_KNOWN_OPERATIONS = _COMPARISONS | {"SORT"}


def _validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SQL_IDENTIFIER.fullmatch(value):
        raise StructuredRegistryError(f"unsafe trusted {label}: {value!r}")


@dataclass(frozen=True, slots=True)
class TrustedTable:
    logical_table_id: str
    schema_name: str
    table_name: str
    source_row_id_column: str = "source_row_id"
    logical_table_id_column: str = "logical_table_id"
    raw_record_column: str = "raw_record"
    parse_statuses_column: str = "parse_statuses"

    def __post_init__(self) -> None:
        if not self.logical_table_id:
            raise StructuredRegistryError("logical_table_id must not be empty")
        for label, value in (
            ("schema identifier", self.schema_name),
            ("table identifier", self.table_name),
            ("source-row identifier", self.source_row_id_column),
            ("logical-table identifier", self.logical_table_id_column),
            ("raw-record identifier", self.raw_record_column),
            ("parse-status identifier", self.parse_statuses_column),
        ):
            _validate_identifier(value, label)


@dataclass(frozen=True, slots=True)
class TrustedField:
    semantic_key: str
    logical_table_id: str
    source_column: str
    qualified_name: str
    physical_column: str
    target_type: TargetType
    allowed_operations: frozenset[str]
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.semantic_key or not self.semantic_key.strip():
            raise StructuredRegistryError("semantic_key must not be blank")
        if not self.logical_table_id:
            raise StructuredRegistryError("logical_table_id must not be empty")
        if not self.source_column or not self.qualified_name:
            raise StructuredRegistryError("source column identity must be complete")
        _validate_identifier(self.physical_column, "field identifier")
        operations = frozenset(str(operation).upper() for operation in self.allowed_operations)
        unknown = operations - _KNOWN_OPERATIONS
        if unknown:
            raise StructuredRegistryError(
                f"unknown allowed operations for {self.semantic_key}: {sorted(unknown)}"
            )
        object.__setattr__(self, "allowed_operations", operations)


class TrustedQueryRegistry:
    """Immutable lookup boundary for queryable tables and confirmed fields."""

    def __init__(
        self,
        tables: Iterable[TrustedTable],
        fields: Iterable[TrustedField],
    ) -> None:
        table_map: dict[str, TrustedTable] = {}
        for table in tables:
            if table.logical_table_id in table_map:
                raise StructuredRegistryError(
                    f"duplicate trusted table: {table.logical_table_id}"
                )
            table_map[table.logical_table_id] = table

        field_map: dict[tuple[str, str], TrustedField] = {}
        for field in fields:
            if field.logical_table_id not in table_map:
                raise StructuredRegistryError(
                    f"field references unknown table: {field.logical_table_id}"
                )
            identity = (field.logical_table_id, field.semantic_key)
            if identity in field_map:
                raise StructuredRegistryError(
                    f"duplicate trusted field: {field.logical_table_id}.{field.semantic_key}"
                )
            field_map[identity] = field

        self._tables: Mapping[str, TrustedTable] = MappingProxyType(table_map)
        self._fields: Mapping[tuple[str, str], TrustedField] = MappingProxyType(field_map)

    def table(self, product_scope: str) -> TrustedTable | None:
        return self._tables.get(product_scope)

    def field(self, product_scope: str, semantic_key: str) -> TrustedField | None:
        return self._fields.get((product_scope, semantic_key))

    @property
    def table_count(self) -> int:
        return len(self._tables)

    @property
    def field_count(self) -> int:
        return len(self._fields)


def _record_value(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)


def build_trusted_query_registry(
    staging_schema: Any,
    core_mappings: Iterable[Any],
) -> TrustedQueryRegistry:
    """Join CONFIRMED semantic fields to generated staging identifiers.

    The loose input protocol keeps this boundary independent of report-model
    implementation details.  Missing or mismatched staging fields fail closed.
    """

    tables = tuple(
        TrustedTable(
            logical_table_id=table.logical_table_id,
            schema_name=table.db_schema_name,
            table_name=table.db_table_name,
        )
        for table in staging_schema.tables
    )
    trusted_fields: list[TrustedField] = []
    for mapping in core_mappings:
        status = str(_record_value(mapping, "semantic_status") or "").upper()
        if status != "CONFIRMED":
            continue
        logical_table_id = str(_record_value(mapping, "logical_table_id") or "")
        qualified_name = str(_record_value(mapping, "qualified_name") or "")
        try:
            table = staging_schema.table_for(logical_table_id)
            column = table.column_for(qualified_name)
        except KeyError as exc:
            raise StructuredRegistryError(
                f"confirmed mapping has no staging column: "
                f"{logical_table_id}.{qualified_name}"
            ) from exc

        mapping_target = str(_record_value(mapping, "target_type") or "").upper()
        if mapping_target != column.target_type.value:
            raise StructuredRegistryError(
                f"target type mismatch for {logical_table_id}.{qualified_name}: "
                f"mapping={mapping_target}, staging={column.target_type.value}"
            )
        operations = _record_value(mapping, "allowed_operations") or ()
        trusted_fields.append(
            TrustedField(
                semantic_key=str(_record_value(mapping, "semantic_field_key") or ""),
                logical_table_id=logical_table_id,
                source_column=str(_record_value(mapping, "source_column") or ""),
                qualified_name=qualified_name,
                physical_column=column.db_column_name,
                target_type=column.target_type,
                allowed_operations=frozenset(str(value) for value in operations),
            )
        )
    return TrustedQueryRegistry(tables, trusted_fields)


__all__ = [
    "TrustedField",
    "TrustedQueryRegistry",
    "TrustedTable",
    "build_trusted_query_registry",
]
