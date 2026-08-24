"""G3 semantic gate layered before the existing structured compiler.

This planner is an opt-in G3 entry point.  It does not mutate or replace the
G2 trusted-query registry; after semantic approval it delegates SQL generation
to the same closed ``StructuredQueryCompiler`` used by G2.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from mappings.semantic.models import (
    ClaimStatus,
    OperationStatus,
    SemanticFieldApproval,
)
from mappings.semantic.registry import get_semantic_field_approval
from pipeline.structured.schema import StagingSchemaSpec

from .compiler import CompiledStructuredQuery, StructuredQueryCompiler
from .contracts import (
    SemanticGateTrace,
    StructuredQueryContract,
    StructuredQueryStatus,
)
from .errors import StructuredQueryValidationError
from .registry import TrustedField, TrustedQueryRegistry, TrustedTable


ApprovalLookup = Callable[[str, str], SemanticFieldApproval | None]


class SemanticQueryUnsupportedError(StructuredQueryValidationError):
    """A query blocked before SQL because semantic approval is insufficient."""

    status = StructuredQueryStatus.UNSUPPORTED

    def __init__(
        self,
        message: str,
        semantic_gate_trace: tuple[SemanticGateTrace, ...],
    ) -> None:
        super().__init__(message)
        self.semantic_gate_trace = semantic_gate_trace


class SemanticGatedQueryPlanner:
    """Compile only operations explicitly OPEN in the G3 semantic registry."""

    def __init__(
        self,
        staging_schema: StagingSchemaSpec,
        approval_lookup: ApprovalLookup = get_semantic_field_approval,
    ) -> None:
        self._staging_schema = staging_schema
        self._approval_lookup = approval_lookup

    @staticmethod
    def _blocked(
        *,
        trace: list[SemanticGateTrace],
        table: str,
        semantic_key: str | None,
        operation: str | None,
        summary: str,
        message: str,
    ) -> None:
        trace.append(
            SemanticGateTrace(
                gate="semantic_approval",
                logical_table_id=table,
                semantic_key=semantic_key,
                operation=operation,
                status=StructuredQueryStatus.UNSUPPORTED,
                summary=summary,
            )
        )
        raise SemanticQueryUnsupportedError(message, tuple(trace))

    def _approval(
        self,
        *,
        table: str,
        semantic_key: str,
        trace: list[SemanticGateTrace],
    ) -> SemanticFieldApproval:
        approval = self._approval_lookup(table, semantic_key)
        if approval is None:
            self._blocked(
                trace=trace,
                table=table,
                semantic_key=semantic_key,
                operation=None,
                summary="unknown_semantic_key",
                message=f"unsupported semantic key: {table}.{semantic_key}",
            )
        assert approval is not None
        if approval.concept.status is not ClaimStatus.CONFIRMED:
            self._blocked(
                trace=trace,
                table=table,
                semantic_key=semantic_key,
                operation=None,
                summary="concept_not_confirmed",
                message=f"semantic concept is not confirmed: {table}.{semantic_key}",
            )
        trace.append(
            SemanticGateTrace(
                gate="semantic_approval",
                logical_table_id=table,
                semantic_key=semantic_key,
                operation=None,
                status=StructuredQueryStatus.SUPPORTED,
                summary="concept_confirmed",
            )
        )
        return approval

    def _require_open_operation(
        self,
        *,
        approval: SemanticFieldApproval,
        operation: str,
        trace: list[SemanticGateTrace],
    ) -> None:
        decision = next(
            (
                item
                for item in approval.operations
                if item.operation == operation
            ),
            None,
        )
        if decision is None or decision.status is not OperationStatus.OPEN:
            self._blocked(
                trace=trace,
                table=approval.logical_table_id,
                semantic_key=approval.semantic_key,
                operation=operation,
                summary="operation_not_open",
                message=(
                    f"semantic operation is not open: "
                    f"{approval.logical_table_id}.{approval.semantic_key}.{operation}"
                ),
            )
        trace.append(
            SemanticGateTrace(
                gate="semantic_approval",
                logical_table_id=approval.logical_table_id,
                semantic_key=approval.semantic_key,
                operation=operation,
                status=StructuredQueryStatus.SUPPORTED,
                summary="operation_open",
            )
        )

    def compile(self, query: StructuredQueryContract) -> CompiledStructuredQuery:
        trace: list[SemanticGateTrace] = []
        try:
            staging_table = self._staging_schema.table_for(query.product_scope)
        except KeyError:
            self._blocked(
                trace=trace,
                table=query.product_scope,
                semantic_key=None,
                operation=None,
                summary="unknown_product_scope",
                message=f"unknown product scope: {query.product_scope}",
            )
            raise AssertionError("unreachable")

        trace.append(
            SemanticGateTrace(
                gate="product_scope",
                logical_table_id=query.product_scope,
                semantic_key=None,
                operation=None,
                status=StructuredQueryStatus.SUPPORTED,
                summary="product_scope_selected",
            )
        )

        requested_keys = tuple(
            dict.fromkeys(
                (
                    *query.projections,
                    *(clause.field for clause in query.filters),
                    *((query.sort.field,) if query.sort is not None else ()),
                )
            )
        )
        approvals = {
            semantic_key: self._approval(
                table=query.product_scope,
                semantic_key=semantic_key,
                trace=trace,
            )
            for semantic_key in requested_keys
        }
        compiler_operations: dict[str, set[str]] = {
            semantic_key: set() for semantic_key in requested_keys
        }

        for clause in query.filters:
            operation = clause.operator.value
            approval = approvals[clause.field]
            self._require_open_operation(
                approval=approval,
                operation=operation,
                trace=trace,
            )
            compiler_operations[clause.field].add(operation)

        if query.sort is not None:
            operation = f"SORT_{query.sort.direction.value}"
            approval = approvals[query.sort.field]
            self._require_open_operation(
                approval=approval,
                operation=operation,
                trace=trace,
            )
            compiler_operations[query.sort.field].add("SORT")

        for semantic_key in query.projections:
            if not compiler_operations[semantic_key]:
                self._blocked(
                    trace=trace,
                    table=query.product_scope,
                    semantic_key=semantic_key,
                    operation="PROJECT",
                    summary="projection_has_no_open_runtime_operation",
                    message=(
                        "projection requires an OPEN runtime operation in the "
                        f"same query: {query.product_scope}.{semantic_key}"
                    ),
                )

        if query.sort is not None and query.limit is not None:
            trace.append(
                SemanticGateTrace(
                    gate="query_shape",
                    logical_table_id=query.product_scope,
                    semantic_key=query.sort.field,
                    operation="TOP_N",
                    status=StructuredQueryStatus.SUPPORTED,
                    summary=f"top_{query.limit}_ready",
                )
            )

        trusted_fields: list[TrustedField] = []
        for semantic_key, approval in approvals.items():
            try:
                column = staging_table.column_for(approval.qualified_name)
            except KeyError:
                self._blocked(
                    trace=trace,
                    table=query.product_scope,
                    semantic_key=semantic_key,
                    operation=None,
                    summary="staging_source_identity_missing",
                    message=(
                        "semantic approval has no unambiguous staging column: "
                        f"{query.product_scope}.{approval.qualified_name}"
                    ),
                )
                raise AssertionError("unreachable")
            trusted_fields.append(
                TrustedField(
                    semantic_key=semantic_key,
                    logical_table_id=query.product_scope,
                    source_column=approval.source_column,
                    qualified_name=approval.qualified_name,
                    physical_column=column.db_column_name,
                    target_type=column.target_type,
                    allowed_operations=frozenset(
                        compiler_operations[semantic_key]
                    ),
                )
            )

        trusted_table = TrustedTable(
            logical_table_id=staging_table.logical_table_id,
            schema_name=staging_table.db_schema_name,
            table_name=staging_table.db_table_name,
        )
        compiler = StructuredQueryCompiler(
            TrustedQueryRegistry((trusted_table,), trusted_fields)
        )
        return replace(
            compiler.compile(query),
            planning_status=StructuredQueryStatus.SUPPORTED,
            semantic_gate_trace=tuple(trace),
        )


class LayeredStructuredQueryPlanner:
    """Preserve G2 compilation while routing registered G3 keys through its gate."""

    def __init__(
        self,
        g2_planner: StructuredQueryCompiler,
        semantic_planner: SemanticGatedQueryPlanner,
        approval_lookup: ApprovalLookup = get_semantic_field_approval,
    ) -> None:
        self._g2_planner = g2_planner
        self._semantic_planner = semantic_planner
        self._approval_lookup = approval_lookup

    @property
    def semantic_planner(self) -> SemanticGatedQueryPlanner:
        return self._semantic_planner

    def compile(self, query: StructuredQueryContract) -> CompiledStructuredQuery:
        requested_keys = tuple(
            dict.fromkeys(
                (
                    *query.projections,
                    *(clause.field for clause in query.filters),
                    *((query.sort.field,) if query.sort is not None else ()),
                )
            )
        )
        g3_keys = {
            semantic_key
            for semantic_key in requested_keys
            if self._approval_lookup(query.product_scope, semantic_key) is not None
        }
        if not g3_keys:
            return self._g2_planner.compile(query)
        if len(g3_keys) != len(requested_keys):
            trace = (
                SemanticGateTrace(
                    gate="planner_boundary",
                    logical_table_id=query.product_scope,
                    semantic_key=None,
                    operation=None,
                    status=StructuredQueryStatus.UNSUPPORTED,
                    summary="mixed_g2_g3_plan_not_approved",
                ),
            )
            raise SemanticQueryUnsupportedError(
                "mixing G2 and G3 semantic fields is not approved",
                trace,
            )
        return self._semantic_planner.compile(query)


__all__ = [
    "LayeredStructuredQueryPlanner",
    "SemanticGatedQueryPlanner",
    "SemanticQueryUnsupportedError",
]
