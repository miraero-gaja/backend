"""Deterministic Priority-A structured query boundary."""

from .compiler import CompiledStructuredQuery, StructuredQueryCompiler
from .contracts import (
    AggregateFunction,
    FilterOperator,
    SemanticGateTrace,
    SortDirection,
    StructuredFilter,
    StructuredQueryContract,
    StructuredQueryStatus,
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
    StructuredQueryPlanner,
)
from .registry import (
    TrustedField,
    TrustedQueryRegistry,
    TrustedTable,
    build_trusted_query_registry,
)
from .semantic_gate import (
    LayeredStructuredQueryPlanner,
    SemanticGatedQueryPlanner,
    SemanticQueryUnsupportedError,
)

__all__ = [
    "AggregateFunction",
    "AsyncQueryBackend",
    "CompiledStructuredQuery",
    "FilterOperator",
    "LayeredStructuredQueryPlanner",
    "PsycopgQueryBackend",
    "SemanticGateTrace",
    "SemanticGatedQueryPlanner",
    "SemanticQueryUnsupportedError",
    "SortDirection",
    "StructuredExecutionResult",
    "StructuredFilter",
    "StructuredQueryCompiler",
    "StructuredQueryContract",
    "StructuredQueryStatus",
    "StructuredQueryError",
    "StructuredQueryExecutor",
    "StructuredQueryPlanner",
    "StructuredQueryValidationError",
    "StructuredRegistryError",
    "StructuredSort",
    "TrustedField",
    "TrustedQueryRegistry",
    "TrustedTable",
    "build_trusted_query_registry",
]
