"""Injectable structured-query execution without owning application globals."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.evidence.models import (
    AggregateEvidence,
    EvidenceItem,
    ScalarValue,
    SupportStatus,
)

from .compiler import CompiledStructuredQuery
from .contracts import (
    SemanticGateTrace,
    StructuredQueryContract,
    StructuredQueryStatus,
)
from .errors import StructuredQueryValidationError
from .evidence import row_to_candidate, row_to_evidence


class AsyncQueryBackend(Protocol):
    async def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any],
    ) -> Sequence[Mapping[str, Any]]: ...


class StructuredQueryPlanner(Protocol):
    """Compiler-compatible planning boundary used by the executor."""

    def compile(
        self,
        query: StructuredQueryContract,
    ) -> CompiledStructuredQuery: ...


def structured_query_fingerprint(query: StructuredQueryContract) -> str:
    payload = query.model_dump(mode="json")
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class StructuredExecutionResult:
    query_fingerprint: str
    candidates: tuple[dict[str, ScalarValue], ...]
    columns: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    compiled_query: CompiledStructuredQuery
    aggregate_evidence: tuple[AggregateEvidence, ...] = ()
    status: StructuredQueryStatus = StructuredQueryStatus.SUPPORTED
    semantic_gate_trace: tuple[SemanticGateTrace, ...] = ()


class StructuredQueryExecutor:
    def __init__(
        self,
        compiler: StructuredQueryPlanner,
        backend: AsyncQueryBackend,
    ) -> None:
        self._compiler = compiler
        self._backend = backend

    @property
    def planner(self) -> StructuredQueryPlanner:
        """Expose the immutable planning dependency for wiring inspection."""

        return self._compiler

    async def execute(
        self, query: StructuredQueryContract
    ) -> StructuredExecutionResult:
        compiled = self._compiler.compile(query)
        rows = tuple(await self._backend.fetch_all(compiled.sql, compiled.parameters))
        if compiled.is_count:
            if len(rows) != 1 or "__count" not in rows[0]:
                raise StructuredQueryValidationError(
                    "COUNT query returned an invalid result shape"
                )
            value = rows[0]["__count"]
            if isinstance(value, bool):
                raise StructuredQueryValidationError("COUNT result is not an integer")
            try:
                count = int(value)
            except (TypeError, ValueError) as exc:
                raise StructuredQueryValidationError(
                    "COUNT result is not an integer"
                ) from exc
            if count < 0:
                raise StructuredQueryValidationError("COUNT result cannot be negative")
            candidates = ({"count": count},)
            columns = ("count",)
            evidence: tuple[EvidenceItem, ...] = ()
            aggregate_evidence = (
                AggregateEvidence(
                    source_table=query.product_scope,
                    operation="COUNT",
                    value=count,
                    query_fingerprint=structured_query_fingerprint(query),
                    condition_ids=tuple(
                        selection.condition_id
                        for selection in compiled.evidence_fields
                        if selection.condition_id is not None
                    ),
                    decision=SupportStatus.SUPPORTED,
                ),
            )
        else:
            candidates = tuple(row_to_candidate(row, compiled) for row in rows)
            evidence = tuple(
                item for row in rows for item in row_to_evidence(row, compiled)
            )
            columns = tuple(
                selection.field.semantic_key for selection in compiled.projected_fields
            )
            aggregate_evidence = ()
        return StructuredExecutionResult(
            query_fingerprint=structured_query_fingerprint(query),
            candidates=candidates,
            columns=columns,
            evidence=evidence,
            aggregate_evidence=aggregate_evidence,
            compiled_query=compiled,
            status=(
                compiled.planning_status
                if compiled.is_count or candidates
                else StructuredQueryStatus.NO_MATCH
            ),
            semantic_gate_trace=compiled.semantic_gate_trace,
        )


class PsycopgQueryBackend:
    """Small async facade over an injected, owned psycopg-style connection.

    ``connection_factory`` must return a new connection for each call.  The
    backend closes it after the read and never commits or executes write SQL.
    No URL or secret is retained here.
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    async def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any],
    ) -> Sequence[Mapping[str, Any]]:
        return await asyncio.to_thread(self._fetch_sync, sql, tuple(parameters))

    def _fetch_sync(
        self,
        sql: str,
        parameters: tuple[Any, ...],
    ) -> Sequence[Mapping[str, Any]]:
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, parameters)
                description = cursor.description
                rows = cursor.fetchall()
            if description is None:
                raise StructuredQueryValidationError("query returned no row description")
            names = tuple(
                str(column.name if hasattr(column, "name") else column[0])
                for column in description
            )
            converted: list[Mapping[str, Any]] = []
            for row in rows:
                if isinstance(row, Mapping):
                    converted.append(dict(row))
                else:
                    converted.append(dict(zip(names, row, strict=True)))
            return tuple(converted)
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()


__all__ = [
    "AsyncQueryBackend",
    "PsycopgQueryBackend",
    "StructuredExecutionResult",
    "StructuredQueryPlanner",
    "StructuredQueryExecutor",
    "structured_query_fingerprint",
]
