"""Deterministic Priority-A structured query boundary."""

from .compiler import CompiledStructuredQuery, StructuredQueryCompiler
from .contracts import (
    AggregateFunction,
    FilterOperator,
    SortDirection,
    StructuredFilter,
    StructuredQueryContract,
    StructuredSort,
)
from .errors import (
    StructuredQueryError,
    StructuredQueryValidationError,
    StructuredRegistryError,
)
from .executor import (
    AsyncQueryBackend,
    PsycopgQueryBackend,
    StructuredExecutionResult,
    StructuredQueryExecutor,
)
from .registry import (
    TrustedField,
    TrustedQueryRegistry,
    TrustedTable,
    build_trusted_query_registry,
)

__all__ = [
    "AggregateFunction",
    "AsyncQueryBackend",
    "CompiledStructuredQuery",
    "FilterOperator",
    "PsycopgQueryBackend",
    "SortDirection",
    "StructuredExecutionResult",
    "StructuredFilter",
    "StructuredQueryCompiler",
    "StructuredQueryContract",
    "StructuredQueryError",
    "StructuredQueryExecutor",
    "StructuredQueryValidationError",
    "StructuredRegistryError",
    "StructuredSort",
    "TrustedField",
    "TrustedQueryRegistry",
    "TrustedTable",
    "build_trusted_query_registry",
]
