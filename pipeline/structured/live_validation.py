"""Read-only Live Structured Query Validation against an already-loaded
PostgreSQL staging database.

Scope (G2-B only): prove that the existing production path

    StructuredQueryContract -> TrustedQueryRegistry -> StructuredQueryCompiler
    -> parameter binding -> StructuredQueryExecutor -> PostgreSQL SELECT
    -> result -> Evidence conversion

returns correct results against the four already-loaded staging tables, for
the seven required query shapes, using only currently CONFIRMED Priority A
fields.

This module never loads, replaces, inserts, updates, or deletes data.  Every
statement it issues -- through the production compiler/executor and through
its small independent verification oracle -- is a SELECT.  No row value,
credential, or connection string is ever placed in the returned dictionary;
only counts, booleans, and field/table identifiers are reported, matching the
existing G2-B report policy in ``reports.py``.

Deliberately out of scope here (left for later gates, per team decision):
Natural Language parsing, HyperCLOVA X, Ontology, PRBD01N001/PREF02N001
mapping expansion, Graph, Vector, default LIMIT/timeout hardening, whitespace
normalization policy, and the EvidenceValidator SUPPORTED policy.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.evidence.models import SupportStatus
from app.structured.compiler import StructuredQueryCompiler
from app.structured.contracts import (
    AggregateFunction,
    FilterOperator,
    SortDirection,
    StructuredFilter,
    StructuredQueryContract,
    StructuredSort,
)
from app.structured.executor import PsycopgQueryBackend, StructuredQueryExecutor
from app.structured.registry import TrustedQueryRegistry


class LiveQueryValidationError(RuntimeError):
    """Raised when a live validation shape cannot be safely executed."""


# Fields already known (G2-A/G1) to have a hypothetical-trim collision.  The
# whitespace preserve/trim policy is an explicit G3 Semantic Grounding
# decision, not a G2-B blocker; live validation simply avoids selecting these
# as probe fields rather than pre-judging that policy here.
_WHITESPACE_CONFLICT_FIELDS = frozenset(
    {
        ("PRBD01N001", "PD_ENG_NM#1"),
        ("PRBD01N001", "PD_PBCM#1"),
        ("PRBD01N001", "BD_KND#1"),
        ("PREF01N001", "cu_base_index#1"),
        ("PREF01N001", "pd_dvid_cycl#1"),
        ("PREF01N001", "pd_mkt_nm#1"),
    }
)

# Explicit, known-safe CONFIRMED Priority A fields used as live-validation
# probes.  Picked from the existing PREF01N001 CONFIRMED set (mirrors the
# table already used by the offline ``_compile_query_preflight`` shapes) and
# checked against ``_WHITESPACE_CONFLICT_FIELDS`` at run time so a future
# registry change fails closed instead of silently drifting onto a
# conflicted field.
_PRODUCT_SCOPE = "PREF01N001"
_EQ_FIELD = "pref01.product_code"
_EQ_FIELD_2 = "pref01.exchange_code"
_RANGE_SORT_FIELD = "pref01.listed_share_count"
_ROW_LIMIT = 5
_TOP_N_LIMIT = 3


def _require_probe_field(registry: TrustedQueryRegistry, semantic_key: str, operation: str):
    field = registry.field(_PRODUCT_SCOPE, semantic_key)
    if field is None:
        raise LiveQueryValidationError(
            f"live validation probe field is not CONFIRMED: {_PRODUCT_SCOPE}.{semantic_key}"
        )
    if operation not in field.allowed_operations:
        raise LiveQueryValidationError(
            f"live validation probe field {semantic_key} does not allow {operation}"
        )
    if (field.logical_table_id, field.qualified_name) in _WHITESPACE_CONFLICT_FIELDS:
        raise LiveQueryValidationError(
            f"refusing to use a whitespace-conflicted field as a live probe: {semantic_key}"
        )
    return field


class _OracleConnection:
    """A short-lived, read-only helper for independent cross-checks.

    This never runs anything but SELECT and never shares a connection across
    calls with the production backend, so it cannot influence -- or be
    influenced by -- the path under test.
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def fetch_all(self, sql: str, parameters: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(parameters))
                rows = cursor.fetchall()
            return [tuple(row) for row in rows]
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()

    def fetch_one(self, sql: str, parameters: Sequence[Any] = ()) -> tuple[Any, ...] | None:
        rows = self.fetch_all(sql, parameters)
        return rows[0] if rows else None


def _quote(identifier: str) -> str:
    return f'"{identifier}"'


def _oracle_select(
    table_qualified_sql_name: str,
    physical_column: str,
    *,
    extra_where: str | None = None,
) -> str:
    where = f'{_quote(physical_column)} IS NOT NULL'
    if extra_where:
        where = f"{where} AND {extra_where}"
    return (
        f"SELECT {_quote(physical_column)}, \"source_row_id\" "
        f"FROM {table_qualified_sql_name} WHERE {where} "
        f'ORDER BY "source_row_id" ASC LIMIT 1'
    )


def _run_production(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    query: StructuredQueryContract,
):
    compiler = StructuredQueryCompiler(registry)
    backend = PsycopgQueryBackend(connection_factory)
    executor = StructuredQueryExecutor(compiler, backend)
    return asyncio.run(executor.execute(query))


@dataclass(frozen=True, slots=True)
class ShapeOutcome:
    name: str
    status: str
    reason: str
    checks: Mapping[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "checks": dict(self.checks),
        }


def _fail(name: str, reason: str, checks: Mapping[str, bool] | None = None) -> ShapeOutcome:
    return ShapeOutcome(name=name, status="FAIL", reason=reason, checks=dict(checks or {}))


def _pass(name: str, reason: str, checks: Mapping[str, bool]) -> ShapeOutcome:
    return ShapeOutcome(name=name, status="PASS", reason=reason, checks=dict(checks))


def _validate_eq(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    oracle: _OracleConnection,
    eq_field,
    table_sql_name: str,
) -> ShapeOutcome:
    seed = oracle.fetch_one(_oracle_select(table_sql_name, eq_field.physical_column))
    if seed is None:
        return _fail("eq", "no non-null sample value was available for the EQ probe field")
    sample_value, seed_row_id = seed

    result = _run_production(
        registry,
        connection_factory,
        StructuredQueryContract(
            product_scope=_PRODUCT_SCOPE,
            filters=(StructuredFilter(field=_EQ_FIELD, operator=FilterOperator.EQ, value=sample_value),),
            projections=(_EQ_FIELD,),
            limit=_ROW_LIMIT,
        ),
    )

    oracle_count = oracle.fetch_one(
        f"SELECT count(*) FROM {table_sql_name} WHERE {_quote(eq_field.physical_column)} = %s",
        (sample_value,),
    )
    oracle_matches = int(oracle_count[0]) if oracle_count else 0

    checks = {
        "returned_at_least_one_row": len(result.candidates) >= 1,
        "returned_row_count_is_bounded_by_limit": len(result.candidates) <= _ROW_LIMIT,
        "seed_row_was_returned": seed_row_id in {item.source_row_id for item in result.evidence},
        "all_rows_satisfy_condition": all(
            candidate[eq_field.semantic_key] == sample_value for candidate in result.candidates
        ),
        "row_count_matches_independent_oracle": len(result.candidates) == min(oracle_matches, _ROW_LIMIT),
        "every_row_has_source_row_id": all(bool(item.source_row_id) for item in result.evidence),
        "evidence_source_field_matches": all(
            item.source_field == eq_field.qualified_name for item in result.evidence
        ),
        "evidence_decision_is_supported": all(
            item.decision is SupportStatus.SUPPORTED for item in result.evidence
        ),
    }
    if not all(checks.values()):
        return _fail("eq", "one or more EQ correctness checks failed", checks)
    return _pass("eq", "EQ filter matched the independent oracle count and lineage", checks)


def _validate_range(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    oracle: _OracleConnection,
    range_field,
    table_sql_name: str,
) -> ShapeOutcome:
    minimum = oracle.fetch_one(
        f"SELECT min({_quote(range_field.physical_column)}) FROM {table_sql_name} "
        f"WHERE {_quote(range_field.physical_column)} IS NOT NULL"
    )
    if minimum is None or minimum[0] is None:
        return _fail("range", "no non-null sample value was available for the range probe field")
    threshold = minimum[0]

    result = _run_production(
        registry,
        connection_factory,
        StructuredQueryContract(
            product_scope=_PRODUCT_SCOPE,
            filters=(StructuredFilter(field=_RANGE_SORT_FIELD, operator=FilterOperator.GE, value=threshold),),
            projections=(_RANGE_SORT_FIELD,),
            limit=_ROW_LIMIT,
        ),
    )

    oracle_count_row = oracle.fetch_one(
        f"SELECT count(*) FROM {table_sql_name} WHERE {_quote(range_field.physical_column)} >= %s",
        (threshold,),
    )
    oracle_total = int(oracle_count_row[0]) if oracle_count_row else 0

    checks = {
        "returned_at_least_one_row": len(result.candidates) >= 1,
        "returned_row_count_is_bounded_by_limit": len(result.candidates) <= _ROW_LIMIT,
        "all_rows_satisfy_ge_condition": all(
            Decimal(str(candidate[range_field.semantic_key])) >= Decimal(str(threshold))
            for candidate in result.candidates
            if candidate[range_field.semantic_key] is not None
        ),
        "oracle_has_at_least_as_many_matches": oracle_total >= len(result.candidates),
        "evidence_decision_is_supported": all(
            item.decision is SupportStatus.SUPPORTED for item in result.evidence
        ),
    }
    if not all(checks.values()):
        return _fail("range", "one or more range correctness checks failed", checks)
    return _pass("range", "GE filter satisfied the condition on every returned row", checks)


def _validate_multi_filter(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    oracle: _OracleConnection,
    eq_field,
    eq_field_2,
    table_sql_name: str,
) -> ShapeOutcome:
    seed = oracle.fetch_one(
        f"SELECT {_quote(eq_field.physical_column)}, {_quote(eq_field_2.physical_column)} "
        f"FROM {table_sql_name} WHERE {_quote(eq_field.physical_column)} IS NOT NULL "
        f"AND {_quote(eq_field_2.physical_column)} IS NOT NULL "
        f'ORDER BY "source_row_id" ASC LIMIT 1'
    )
    if seed is None:
        return _fail("multi_filter", "no row has both probe fields populated")
    value_1, value_2 = seed

    result = _run_production(
        registry,
        connection_factory,
        StructuredQueryContract(
            product_scope=_PRODUCT_SCOPE,
            filters=(
                StructuredFilter(field=_EQ_FIELD, operator=FilterOperator.EQ, value=value_1),
                StructuredFilter(field=_EQ_FIELD_2, operator=FilterOperator.EQ, value=value_2),
            ),
            projections=(_EQ_FIELD, _EQ_FIELD_2),
            limit=_ROW_LIMIT,
        ),
    )

    oracle_count_row = oracle.fetch_one(
        f"SELECT count(*) FROM {table_sql_name} "
        f"WHERE {_quote(eq_field.physical_column)} = %s AND {_quote(eq_field_2.physical_column)} = %s",
        (value_1, value_2),
    )
    oracle_matches = int(oracle_count_row[0]) if oracle_count_row else 0

    checks = {
        "returned_at_least_one_row": len(result.candidates) >= 1,
        "returned_row_count_is_bounded_by_limit": len(result.candidates) <= _ROW_LIMIT,
        "all_rows_satisfy_both_conditions": all(
            candidate[eq_field.semantic_key] == value_1
            and candidate[eq_field_2.semantic_key] == value_2
            for candidate in result.candidates
        ),
        "row_count_matches_independent_oracle": len(result.candidates) == min(oracle_matches, _ROW_LIMIT),
        "evidence_decision_is_supported": all(
            item.decision is SupportStatus.SUPPORTED for item in result.evidence
        ),
    }
    if not all(checks.values()):
        return _fail("multi_filter", "one or more multi-filter correctness checks failed", checks)
    return _pass("multi_filter", "both AND-ed EQ filters matched the independent oracle", checks)


def _validate_sort(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    oracle: _OracleConnection,
    sort_field,
    table_sql_name: str,
    *,
    direction: SortDirection,
) -> ShapeOutcome:
    name = "sort_asc" if direction is SortDirection.ASC else "sort_desc"
    result = _run_production(
        registry,
        connection_factory,
        StructuredQueryContract(
            product_scope=_PRODUCT_SCOPE,
            projections=(_RANGE_SORT_FIELD,),
            sort=StructuredSort(field=_RANGE_SORT_FIELD, direction=direction),
            limit=_ROW_LIMIT,
        ),
    )
    values = [candidate[sort_field.semantic_key] for candidate in result.candidates]
    decimals = [Decimal(str(value)) for value in values if value is not None]

    order_sql = "ASC" if direction is SortDirection.ASC else "DESC"
    oracle_rows = oracle.fetch_all(
        f"SELECT \"source_row_id\" FROM {table_sql_name} "
        f"ORDER BY {_quote(sort_field.physical_column)} {order_sql} NULLS LAST, "
        f'"source_row_id" ASC LIMIT {_ROW_LIMIT}'
    )
    oracle_row_ids = [row[0] for row in oracle_rows]
    production_row_ids = [item.source_row_id for item in result.evidence]

    is_monotonic = (
        all(decimals[i] <= decimals[i + 1] for i in range(len(decimals) - 1))
        if direction is SortDirection.ASC
        else all(decimals[i] >= decimals[i + 1] for i in range(len(decimals) - 1))
    )

    checks = {
        "returned_at_least_one_row": len(result.candidates) >= 1,
        "returned_row_count_is_bounded_by_limit": len(result.candidates) <= _ROW_LIMIT,
        "values_are_monotonic_in_requested_direction": is_monotonic,
        "row_sequence_matches_independent_oracle": production_row_ids == oracle_row_ids,
    }
    if not all(checks.values()):
        return _fail(name, "one or more sort-order correctness checks failed", checks)
    return _pass(name, "row sequence matched the independent ORDER BY oracle exactly", checks)


def _validate_top_n(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    oracle: _OracleConnection,
    sort_field,
    table_sql_name: str,
) -> ShapeOutcome:
    result = _run_production(
        registry,
        connection_factory,
        StructuredQueryContract(
            product_scope=_PRODUCT_SCOPE,
            projections=(_RANGE_SORT_FIELD,),
            sort=StructuredSort(field=_RANGE_SORT_FIELD, direction=SortDirection.DESC),
            limit=_TOP_N_LIMIT,
        ),
    )
    oracle_rows = oracle.fetch_all(
        f"SELECT \"source_row_id\" FROM {table_sql_name} "
        f"ORDER BY {_quote(sort_field.physical_column)} DESC NULLS LAST, "
        f'"source_row_id" ASC LIMIT {_TOP_N_LIMIT}'
    )
    oracle_row_ids = [row[0] for row in oracle_rows]
    production_row_ids = [item.source_row_id for item in result.evidence]

    checks = {
        "returned_exactly_n_rows": len(result.candidates) == min(_TOP_N_LIMIT, len(oracle_row_ids)),
        "row_sequence_matches_independent_oracle": production_row_ids == oracle_row_ids,
    }
    if not all(checks.values()):
        return _fail("top_n", "Top-N count or rank order did not match the independent oracle", checks)
    return _pass("top_n", "Top-N rank and count matched the independent oracle exactly", checks)


def _validate_count(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    oracle: _OracleConnection,
    eq_field_2,
    table_sql_name: str,
) -> ShapeOutcome:
    popular = oracle.fetch_one(
        f"SELECT {_quote(eq_field_2.physical_column)}, count(*) AS c FROM {table_sql_name} "
        f"WHERE {_quote(eq_field_2.physical_column)} IS NOT NULL "
        f"GROUP BY {_quote(eq_field_2.physical_column)} ORDER BY c DESC, "
        f"{_quote(eq_field_2.physical_column)} ASC LIMIT 1"
    )
    if popular is None:
        return _fail("count", "no grouped sample value was available for the COUNT probe field")
    value, oracle_count = popular

    result = _run_production(
        registry,
        connection_factory,
        StructuredQueryContract(
            product_scope=_PRODUCT_SCOPE,
            filters=(StructuredFilter(field=_EQ_FIELD_2, operator=FilterOperator.EQ, value=value),),
            aggregate=AggregateFunction.COUNT,
        ),
    )

    produced_count = result.candidates[0]["count"] if result.candidates else None
    checks = {
        "aggregate_value_matches_independent_oracle": produced_count == int(oracle_count),
        "no_fabricated_row_evidence_was_attached": result.evidence == (),
    }
    if not all(checks.values()):
        return _fail("count", "COUNT value did not match the independent oracle", checks)
    return _pass(
        name="count",
        reason=(
            "COUNT matched the independent GROUP BY oracle exactly; "
            f"product_scope={_PRODUCT_SCOPE}, filter_field={_EQ_FIELD_2}, aggregate=COUNT"
        ),
        checks=checks,
    )


def _validate_parse_status_gate(
    registry: TrustedQueryRegistry,
    connection_factory: Callable[[], Any],
    oracle: _OracleConnection,
    eq_field,
    sort_field,
    table_sql_name: str,
) -> ShapeOutcome:
    """Confirm a non-OK parse state can never surface as SUPPORTED evidence."""

    seed = oracle.fetch_one(
        f"SELECT {_quote(eq_field.physical_column)} FROM {table_sql_name} "
        f"WHERE {_quote(eq_field.physical_column)} IS NOT NULL "
        f"AND {_quote(sort_field.physical_column)} IS NULL "
        f'ORDER BY "source_row_id" ASC LIMIT 1'
    )
    if seed is None:
        return ShapeOutcome(
            name="parse_status_gate",
            status="NOT_APPLICABLE",
            reason=(
                "no row currently has a NULL value for the sort/range probe field, "
                "so this run could not exercise the non-OK evidence gate"
            ),
            checks={},
        )
    value = seed[0]
    result = _run_production(
        registry,
        connection_factory,
        StructuredQueryContract(
            product_scope=_PRODUCT_SCOPE,
            filters=(StructuredFilter(field=_EQ_FIELD, operator=FilterOperator.EQ, value=value),),
            projections=(_EQ_FIELD, _RANGE_SORT_FIELD),
            limit=_ROW_LIMIT,
        ),
    )
    null_field_evidence = [
        item for item in result.evidence if item.source_field == sort_field.qualified_name
    ]
    checks = {
        "null_field_evidence_was_returned": len(null_field_evidence) >= 1,
        "null_field_evidence_is_unsupported": all(
            item.decision is SupportStatus.UNSUPPORTED and item.normalized_value is None
            for item in null_field_evidence
        ),
        "other_field_evidence_stayed_supported": any(
            item.decision is SupportStatus.SUPPORTED
            for item in result.evidence
            if item.source_field == eq_field.qualified_name
        ),
    }
    if not all(checks.values()):
        return _fail("parse_status_gate", "a non-OK parse state leaked into SUPPORTED evidence", checks)
    return _pass(
        "parse_status_gate", "a MISSING/NULL field stayed UNSUPPORTED while the row's other field stayed SUPPORTED", checks
    )


def run_live_query_validation(
    connection_factory: Callable[[], Any],
    registry: TrustedQueryRegistry,
) -> dict[str, Any]:
    """Execute the seven required shapes read-only against the loaded tables.

    ``connection_factory`` must open a new read-only-intent PostgreSQL
    connection per call (matching ``PsycopgQueryBackend``'s contract).  Only
    SELECT statements are issued, both through the production compiler and
    through this function's small independent verification oracle.
    """

    table = registry.table(_PRODUCT_SCOPE)
    if table is None:
        raise LiveQueryValidationError(f"trusted registry has no table for {_PRODUCT_SCOPE}")
    table_sql_name = f'"{table.schema_name}"."{table.table_name}"'

    eq_field = _require_probe_field(registry, _EQ_FIELD, "EQ")
    eq_field_2 = _require_probe_field(registry, _EQ_FIELD_2, "EQ")
    range_field = _require_probe_field(registry, _RANGE_SORT_FIELD, "GE")
    sort_field = _require_probe_field(registry, _RANGE_SORT_FIELD, "SORT")

    oracle = _OracleConnection(connection_factory)

    shapes = [
        _validate_eq(registry, connection_factory, oracle, eq_field, table_sql_name),
        _validate_range(registry, connection_factory, oracle, range_field, table_sql_name),
        _validate_multi_filter(registry, connection_factory, oracle, eq_field, eq_field_2, table_sql_name),
        _validate_sort(
            registry, connection_factory, oracle, sort_field, table_sql_name, direction=SortDirection.ASC
        ),
        _validate_sort(
            registry, connection_factory, oracle, sort_field, table_sql_name, direction=SortDirection.DESC
        ),
        _validate_top_n(registry, connection_factory, oracle, sort_field, table_sql_name),
        _validate_count(registry, connection_factory, oracle, eq_field_2, table_sql_name),
    ]
    gate = _validate_parse_status_gate(
        registry, connection_factory, oracle, eq_field, sort_field, table_sql_name
    )

    required_pass = all(shape.status == "PASS" for shape in shapes)
    any_fail = any(shape.status == "FAIL" for shape in shapes) or gate.status == "FAIL"
    status = "PASS" if required_pass and not any_fail else "FAIL"

    return {
        "status": status,
        "product_scope": _PRODUCT_SCOPE,
        "row_limit_used": _ROW_LIMIT,
        "top_n_limit_used": _TOP_N_LIMIT,
        "shapes": {shape.name: shape.to_dict() for shape in shapes},
        "parse_status_gate": gate.to_dict(),
        "query_values_copied_to_report": False,
        "reason": (
            "All seven required shapes matched an independent read-only oracle."
            if status == "PASS"
            else "One or more required shapes failed; see 'shapes' for the specific reason."
        ),
    }


__all__ = [
    "LiveQueryValidationError",
    "run_live_query_validation",
]
