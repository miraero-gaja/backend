"""Deterministic PostgreSQL schema for the four typed staging tables.

Physical identifiers are derived exclusively from validated G2-A rules.  A
caller-supplied natural-language field name is never accepted as a SQL
identifier.  Each source column receives one nullable typed column, while the
exact source values and explicit parse outcomes live in two JSONB envelopes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pipeline.normalize.models import TargetType, TypedRule
from pipeline.normalize.type_rules import canonicalize_declared_type


STAGING_SCHEMA_NAME = "structured_staging"
OFFICIAL_STAGING_COLUMN_COUNTS: dict[str, int] = {
    "PRBD01N001": 40,
    "PREF01N001": 73,
    "PREF02N001": 49,
    "PRFD01N001": 45,
}
OFFICIAL_STAGING_COLUMN_TOTAL = sum(OFFICIAL_STAGING_COLUMN_COUNTS.values())

_LOGICAL_TABLE_ID = re.compile(r"[A-Z][A-Z0-9_]{1,30}", re.ASCII)
_SAFE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}", re.ASCII)
_POSTGRES_TYPES = {
    "text",
    "numeric",
    "bigint",
    "date",
    "timestamp with time zone",
    "timestamp without time zone",
}


class StagingSchemaError(ValueError):
    """Raised when G2-A rules cannot form the official staging shape."""


def quote_identifier(identifier: str) -> str:
    """Quote one already-generated PostgreSQL identifier.

    Rejecting rather than escaping arbitrary input is intentional: this helper
    is for internal schema identifiers, not a general SQL-string API.
    """

    if not isinstance(identifier, str) or not _SAFE_IDENTIFIER.fullmatch(identifier):
        raise StagingSchemaError(f"unsafe generated PostgreSQL identifier: {identifier!r}")
    return f'"{identifier}"'


def _validate_logical_table_id(logical_table_id: str) -> None:
    if not _LOGICAL_TABLE_ID.fullmatch(logical_table_id):
        raise StagingSchemaError(
            f"invalid logical table identifier: {logical_table_id!r}"
        )


def _table_name(logical_table_id: str) -> str:
    _validate_logical_table_id(logical_table_id)
    name = f"stg_{logical_table_id.casefold()}"
    quote_identifier(name)
    return name


def _column_name(position: int, source_column: str) -> str:
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise StagingSchemaError("column position must be a positive integer")
    if not isinstance(source_column, str) or not source_column:
        raise StagingSchemaError("source_column must be a non-empty string")
    slug = re.sub(r"[^a-z0-9]+", "_", source_column.casefold()).strip("_")
    if not slug:
        slug = "field"
    # cNNN_ plus 52 ASCII characters stays below PostgreSQL's 63-byte limit.
    name = f"c{position:03d}_{slug[:52]}"
    quote_identifier(name)
    return name


def _postgres_type_for(target_type: TargetType, declared_type: str) -> str:
    if target_type is TargetType.TEXT:
        return "text"
    if target_type is TargetType.DECIMAL:
        return "numeric"
    if target_type is TargetType.INTEGER:
        return "bigint"
    if target_type is TargetType.DATE:
        return "date"
    if target_type is TargetType.TIMESTAMP:
        declared = canonicalize_declared_type(declared_type)
        return (
            "timestamp with time zone"
            if "with time zone" in declared and "without time zone" not in declared
            else "timestamp without time zone"
        )
    raise StagingSchemaError(f"unsupported typed target: {target_type.value}")


def _postgres_type(rule: TypedRule) -> str:
    try:
        return _postgres_type_for(rule.target_type, rule.declared_type)
    except StagingSchemaError as error:
        raise StagingSchemaError(
            f"unsupported typed target for {rule.logical_table_id}."
            f"{rule.qualified_name}: {rule.target_type.value}"
        ) from error


@dataclass(frozen=True, slots=True)
class StagingColumnSpec:
    """Occurrence-aware mapping from a G2-A rule to one physical DB column."""

    position: int
    logical_table_id: str
    source_column: str
    occurrence: int
    qualified_name: str
    declared_type: str
    target_type: TargetType
    db_column_name: str
    postgres_type: str

    def __post_init__(self) -> None:
        _validate_logical_table_id(self.logical_table_id)
        if isinstance(self.occurrence, bool) or self.occurrence < 1:
            raise StagingSchemaError("occurrence must be a positive integer")
        if self.db_column_name != _column_name(self.position, self.source_column):
            raise StagingSchemaError("DB column name was not generated from source position")
        if self.qualified_name != f"{self.source_column}#{self.occurrence}":
            raise StagingSchemaError("qualified_name is not occurrence-aware")
        if self.postgres_type not in _POSTGRES_TYPES:
            raise StagingSchemaError(f"unsafe PostgreSQL type: {self.postgres_type!r}")
        expected_type = _postgres_type_for(self.target_type, self.declared_type)
        if self.postgres_type != expected_type:
            raise StagingSchemaError("PostgreSQL type differs from declared typed target")

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "logical_table_id": self.logical_table_id,
            "source_column": self.source_column,
            "occurrence": self.occurrence,
            "qualified_name": self.qualified_name,
            "declared_type": self.declared_type,
            "target_type": self.target_type.value,
            "db_column_name": self.db_column_name,
            "postgres_type": self.postgres_type,
            "nullable": True,
        }


@dataclass(frozen=True, slots=True)
class StagingTableSpec:
    """One product-family staging table and all source-column mappings."""

    logical_table_id: str
    db_schema_name: str
    db_table_name: str
    columns: tuple[StagingColumnSpec, ...]

    def __post_init__(self) -> None:
        _validate_logical_table_id(self.logical_table_id)
        if self.db_schema_name != STAGING_SCHEMA_NAME:
            raise StagingSchemaError("staging schema name must use the fixed contract")
        if self.db_table_name != _table_name(self.logical_table_id):
            raise StagingSchemaError("staging table name was not generated internally")
        if not self.columns:
            raise StagingSchemaError("staging table must contain at least one source column")
        for position, column in enumerate(self.columns, start=1):
            if column.position != position:
                raise StagingSchemaError("staging column positions must be contiguous")
            if column.logical_table_id != self.logical_table_id:
                raise StagingSchemaError("staging column belongs to another table")

    @property
    def qualified_sql_name(self) -> str:
        return (
            f"{quote_identifier(self.db_schema_name)}."
            f"{quote_identifier(self.db_table_name)}"
        )

    def column_for(self, qualified_name: str) -> StagingColumnSpec:
        matches = [column for column in self.columns if column.qualified_name == qualified_name]
        if len(matches) != 1:
            raise KeyError(
                f"unknown or ambiguous staging field: "
                f"{self.logical_table_id}.{qualified_name}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_table_id": self.logical_table_id,
            "db_schema_name": self.db_schema_name,
            "db_table_name": self.db_table_name,
            "technical_primary_key": "source_row_id",
            "business_primary_key_enforced": False,
            "lineage_columns": [
                "source_row_id",
                "logical_table_id",
                "source_excel_row",
                "source_file_sha256",
                "source_sheet",
            ],
            "raw_envelope_column": "raw_record",
            "parse_status_envelope_column": "parse_statuses",
            "source_column_count": len(self.columns),
            "columns": [column.to_dict() for column in self.columns],
        }


@dataclass(frozen=True, slots=True)
class StagingSchemaSpec:
    """Validated four-table PostgreSQL typed-staging contract."""

    db_schema_name: str
    tables: tuple[StagingTableSpec, ...]

    def __post_init__(self) -> None:
        if self.db_schema_name != STAGING_SCHEMA_NAME:
            raise StagingSchemaError("staging schema name must use the fixed contract")
        identities = [table.logical_table_id for table in self.tables]
        if len(set(identities)) != len(identities):
            raise StagingSchemaError("staging schema contains duplicate logical tables")
        if any(table.db_schema_name != self.db_schema_name for table in self.tables):
            raise StagingSchemaError("staging table schema name mismatch")

    @property
    def source_column_count(self) -> int:
        return sum(len(table.columns) for table in self.tables)

    def table_for(self, logical_table_id: str) -> StagingTableSpec:
        matches = [table for table in self.tables if table.logical_table_id == logical_table_id]
        if len(matches) != 1:
            raise KeyError(f"unknown or ambiguous logical table: {logical_table_id!r}")
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_schema_name": self.db_schema_name,
            "table_count": len(self.tables),
            "source_column_count": self.source_column_count,
            "all_source_columns_materialized": True,
            "agent_field_exposure_separate_from_storage": True,
            "tables": [table.to_dict() for table in self.tables],
        }


def build_table_spec(
    logical_table_id: str,
    rules: Iterable[TypedRule],
) -> StagingTableSpec:
    """Build one table spec, preserving the declared G2-A rule order."""

    _validate_logical_table_id(logical_table_id)
    table_rules = tuple(rules)
    if not table_rules:
        raise StagingSchemaError(f"no typed rules for {logical_table_id}")

    qualified_names: set[str] = set()
    db_names: set[str] = set()
    columns: list[StagingColumnSpec] = []
    for position, rule in enumerate(table_rules, start=1):
        if rule.logical_table_id != logical_table_id:
            raise StagingSchemaError(
                f"rule table mismatch: expected {logical_table_id}, "
                f"received {rule.logical_table_id}"
            )
        qualified_name = str(rule.qualified_name)
        if qualified_name in qualified_names:
            raise StagingSchemaError(
                f"duplicate occurrence-aware field: {logical_table_id}.{qualified_name}"
            )
        qualified_names.add(qualified_name)
        db_name = _column_name(position, rule.source_column)
        if db_name in db_names:  # position prefix should make this impossible
            raise StagingSchemaError(f"duplicate generated DB column: {db_name}")
        db_names.add(db_name)
        columns.append(
            StagingColumnSpec(
                position=position,
                logical_table_id=logical_table_id,
                source_column=rule.source_column,
                occurrence=rule.occurrence,
                qualified_name=qualified_name,
                declared_type=rule.declared_type,
                target_type=rule.target_type,
                db_column_name=db_name,
                postgres_type=_postgres_type(rule),
            )
        )
    return StagingTableSpec(
        logical_table_id=logical_table_id,
        db_schema_name=STAGING_SCHEMA_NAME,
        db_table_name=_table_name(logical_table_id),
        columns=tuple(columns),
    )


def build_staging_schema(
    rules: Iterable[TypedRule],
    *,
    expected_column_counts: Mapping[str, int] = OFFICIAL_STAGING_COLUMN_COUNTS,
) -> StagingSchemaSpec:
    """Build and validate the complete official four-table/207-column shape.

    Tests may pass an explicit smaller ``expected_column_counts`` mapping.  The
    production default is deliberately strict and cannot silently omit a table
    or source occurrence.
    """

    grouped: dict[str, list[TypedRule]] = defaultdict(list)
    for rule in rules:
        _validate_logical_table_id(rule.logical_table_id)
        grouped[rule.logical_table_id].append(rule)

    expected = dict(expected_column_counts)
    if set(grouped) != set(expected):
        raise StagingSchemaError(
            "typed-rule table identities do not match staging contract: "
            f"expected={sorted(expected)}, observed={sorted(grouped)}"
        )
    tables: list[StagingTableSpec] = []
    for logical_table_id, expected_count in expected.items():
        table = build_table_spec(logical_table_id, grouped[logical_table_id])
        if len(table.columns) != expected_count:
            raise StagingSchemaError(
                f"column count mismatch for {logical_table_id}: "
                f"expected {expected_count}, observed {len(table.columns)}"
            )
        tables.append(table)

    schema = StagingSchemaSpec(STAGING_SCHEMA_NAME, tuple(tables))
    if schema.source_column_count != sum(expected.values()):
        raise StagingSchemaError("total staging source-column count mismatch")
    return schema


def render_create_schema_sql(schema: StagingSchemaSpec) -> str:
    """Render the fixed schema-creation statement."""

    return f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(schema.db_schema_name)}"


def render_create_table_sql(table: StagingTableSpec) -> str:
    """Render deterministic DDL for one source-preserving staging table."""

    logical_literal = table.logical_table_id.replace("'", "''")
    definitions = [
        '"source_row_id" text PRIMARY KEY',
        (
            '"logical_table_id" text NOT NULL '
            f"CHECK (\"logical_table_id\" = '{logical_literal}')"
        ),
        '"source_excel_row" bigint NOT NULL CHECK ("source_excel_row" > 0)',
        '"source_file_sha256" text NOT NULL',
        '"source_sheet" text NOT NULL',
        '"raw_record" jsonb NOT NULL',
        '"parse_statuses" jsonb NOT NULL',
    ]
    definitions.extend(
        f"{quote_identifier(column.db_column_name)} {column.postgres_type} NULL"
        for column in table.columns
    )
    definitions.append(
        'UNIQUE ("source_file_sha256", "source_sheet", "source_excel_row")'
    )
    body = ",\n    ".join(definitions)
    return f"CREATE TABLE IF NOT EXISTS {table.qualified_sql_name} (\n    {body}\n)"


__all__ = [
    "OFFICIAL_STAGING_COLUMN_COUNTS",
    "OFFICIAL_STAGING_COLUMN_TOTAL",
    "STAGING_SCHEMA_NAME",
    "StagingColumnSpec",
    "StagingSchemaError",
    "StagingSchemaSpec",
    "StagingTableSpec",
    "build_staging_schema",
    "build_table_spec",
    "quote_identifier",
    "render_create_schema_sql",
    "render_create_table_sql",
]
