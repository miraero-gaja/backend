"""Injectable structured-query execution without owning application globals."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.evidence.models import EvidenceItem, ScalarValue

from .compiler import CompiledStructuredQuery, StructuredQueryCompiler
from .contracts import StructuredQueryContract
from .errors import StructuredQueryValidationError
from .evidence import row_to_candidate, row_to_evidence


class AsyncQueryBackend(Protocol):
    async def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any],
    ) -> Sequence[Mapping[str, Any]]: ...


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


class StructuredQueryExecutor:
    def __init__(
        self,
        compiler: StructuredQueryCompiler,
        backend: AsyncQueryBackend,
    ) -> None:
        self._compiler = compiler
        self._backend = backend

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
        else:
            candidates = tuple(row_to_candidate(row, compiled) for row in rows)
            evidence = tuple(
                item for row in rows for item in row_to_evidence(row, compiled)
            )
            columns = tuple(
                selection.field.semantic_key for selection in compiled.projected_fields
            )
        return StructuredExecutionResult(
            query_fingerprint=structured_query_fingerprint(query),
            candidates=candidates,
            columns=columns,
            evidence=evidence,
            compiled_query=compiled,
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
    "StructuredQueryExecutor",
    "structured_query_fingerprint",
]
