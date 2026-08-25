"""Production dependency composition for the structured runtime."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request

from app.agent.contracts import RouteHint
from app.agent.executor import ToolExecutor
from app.core.config import Settings
from app.generation import AnswerGenerator, DeterministicAnswerGenerator
from app.structured import (
    AsyncQueryBackend,
    LayeredStructuredQueryPlanner,
    PsycopgQueryBackend,
    SemanticGatedQueryPlanner,
    StructuredQueryCompiler,
    StructuredQueryExecutor,
    StructuredQueryValidationError,
    TrustedQueryRegistry,
    build_trusted_query_registry,
)
from app.tools.cost_rules import CostRulesToolAdapter
from app.tools.graph import GraphToolAdapter
from app.tools.structured import StructuredToolAdapter
from app.tools.vector import VectorToolAdapter
from mappings.core import CORE_FIELD_MAPPINGS, build_core_field_registry
from mappings.semantic import (
    SEMANTIC_FIELD_APPROVALS,
    validate_semantic_registry,
)
from pipeline.normalize.models import TargetType
from pipeline.structured.schema import (
    OFFICIAL_STAGING_COLUMN_COUNTS,
    OFFICIAL_STAGING_COLUMN_TOTAL,
    StagingColumnSpec,
    StagingSchemaSpec,
    StagingTableSpec,
)


_DEFAULT_G2B_STRUCTURED_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "outputs"
    / "reports"
    / "g2b"
    / "g2b_structured_schema.json"
)


class ApplicationCompositionError(RuntimeError):
    """Raised when validated runtime dependencies cannot be composed safely."""


def _object(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ApplicationCompositionError(f"{label} must be an object")
    return value


def _array(value: Any, *, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ApplicationCompositionError(f"{label} must be an array")
    return value


def load_full_staging_schema(
    report_path: str | Path,
) -> StagingSchemaSpec:
    """Restore the validated 4-table/207-column G2-B staging contract."""

    path = Path(report_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ApplicationCompositionError(
            "G2-B structured schema path must be a regular file"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ApplicationCompositionError(
            "G2-B structured schema must be valid UTF-8 JSON"
        ) from error
    root = _object(document, label="G2-B structured schema")
    if root.get("g2b_format_version") != "1.0":
        raise ApplicationCompositionError("unsupported G2-B schema format")
    if root.get("schema_status") != "PASS":
        raise ApplicationCompositionError("G2-B structured schema is not PASS")

    storage = _object(root.get("storage"), label="G2-B storage")
    if storage.get("all_source_columns_materialized") is not True:
        raise ApplicationCompositionError(
            "G2-B storage does not contain every source column"
        )
    if storage.get("agent_field_exposure_separate_from_storage") is not True:
        raise ApplicationCompositionError(
            "G2-B storage and agent exposure are not separated"
        )
    if int(storage.get("table_count", -1)) != len(
        OFFICIAL_STAGING_COLUMN_COUNTS
    ):
        raise ApplicationCompositionError("G2-B storage table count is not official")
    if int(storage.get("source_column_count", -1)) != OFFICIAL_STAGING_COLUMN_TOTAL:
        raise ApplicationCompositionError("G2-B source column count is not official")

    tables: list[StagingTableSpec] = []
    table_entries = _array(storage.get("tables"), label="G2-B storage tables")
    observed_table_ids: list[str] = []
    for table_value in table_entries:
        table = _object(table_value, label="G2-B storage table")
        logical_table_id = str(table.get("logical_table_id", ""))
        observed_table_ids.append(logical_table_id)
        expected_count = OFFICIAL_STAGING_COLUMN_COUNTS.get(logical_table_id)
        if expected_count is None:
            raise ApplicationCompositionError(
                f"unexpected G2-B logical table: {logical_table_id!r}"
            )
        column_entries = _array(
            table.get("columns"),
            label=f"{logical_table_id} columns",
        )
        if len(column_entries) != expected_count:
            raise ApplicationCompositionError(
                f"{logical_table_id} column count is not official"
            )
        columns: list[StagingColumnSpec] = []
        for column_value in column_entries:
            column = _object(
                column_value,
                label=f"{logical_table_id} column",
            )
            if column.get("nullable") is not True:
                raise ApplicationCompositionError(
                    f"{logical_table_id} source column must remain nullable"
                )
            try:
                target_type = TargetType(str(column.get("target_type", "")))
                columns.append(
                    StagingColumnSpec(
                        position=int(column["position"]),
                        logical_table_id=str(column["logical_table_id"]),
                        source_column=str(column["source_column"]),
                        occurrence=int(column["occurrence"]),
                        qualified_name=str(column["qualified_name"]),
                        declared_type=str(column["declared_type"]),
                        target_type=target_type,
                        db_column_name=str(column["db_column_name"]),
                        postgres_type=str(column["postgres_type"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ApplicationCompositionError(
                    f"invalid G2-B column contract for {logical_table_id}"
                ) from error
        try:
            tables.append(
                StagingTableSpec(
                    logical_table_id=logical_table_id,
                    db_schema_name=str(table.get("db_schema_name", "")),
                    db_table_name=str(table.get("db_table_name", "")),
                    columns=tuple(columns),
                )
            )
        except ValueError as error:
            raise ApplicationCompositionError(
                f"invalid G2-B table contract for {logical_table_id}"
            ) from error

    if observed_table_ids != list(OFFICIAL_STAGING_COLUMN_COUNTS):
        raise ApplicationCompositionError(
            "G2-B table order or identities are not official"
        )
    try:
        schema = StagingSchemaSpec(
            db_schema_name=str(storage.get("db_schema_name", "")),
            tables=tuple(tables),
        )
    except ValueError as error:
        raise ApplicationCompositionError(
            "invalid G2-B full staging schema"
        ) from error
    if schema.source_column_count != OFFICIAL_STAGING_COLUMN_TOTAL:
        raise ApplicationCompositionError("restored staging schema is incomplete")
    return schema


class UnavailableStructuredBackend:
    """Configured fail-closed backend used when DATABASE_URL is absent."""

    async def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any],
    ) -> Sequence[Mapping[str, Any]]:
        del sql, parameters
        raise StructuredQueryValidationError(
            "structured database is not configured"
        )


def _configured_backend(settings: Settings) -> AsyncQueryBackend:
    database_url = settings.database_url
    if database_url is None:
        return UnavailableStructuredBackend()

    def connection_factory():
        import psycopg

        return psycopg.connect(
            database_url.get_secret_value(),
            connect_timeout=5,
        )

    return PsycopgQueryBackend(connection_factory)


@dataclass(frozen=True, slots=True)
class ApplicationRuntime:
    staging_schema: StagingSchemaSpec
    g2_registry: TrustedQueryRegistry
    semantic_planner: SemanticGatedQueryPlanner
    structured_planner: LayeredStructuredQueryPlanner
    structured_executor: StructuredQueryExecutor
    tool_executor: ToolExecutor
    answer_generator: AnswerGenerator


def build_application_runtime(
    settings: Settings,
    *,
    structured_backend: AsyncQueryBackend | None = None,
    structured_schema_path: str | Path | None = None,
    answer_generator: AnswerGenerator | None = None,
) -> ApplicationRuntime:
    """Compose G2-preserving and G3-gated structured runtime dependencies."""

    schema = load_full_staging_schema(
        structured_schema_path or _DEFAULT_G2B_STRUCTURED_SCHEMA_PATH
    )
    core_registry = build_core_field_registry()
    if core_registry["validation"]["is_valid"] is not True:
        raise ApplicationCompositionError("G2 core field registry is invalid")
    validate_semantic_registry(SEMANTIC_FIELD_APPROVALS)

    g2_registry = build_trusted_query_registry(schema, CORE_FIELD_MAPPINGS)
    g2_planner = StructuredQueryCompiler(g2_registry)
    semantic_planner = SemanticGatedQueryPlanner(schema)
    structured_planner = LayeredStructuredQueryPlanner(
        g2_planner,
        semantic_planner,
    )
    structured_executor = StructuredQueryExecutor(
        structured_planner,
        (
            structured_backend
            if structured_backend is not None
            else _configured_backend(settings)
        ),
    )
    tool_executor = ToolExecutor(
        {
            RouteHint.STRUCTURED: StructuredToolAdapter(structured_executor),
            RouteHint.GRAPH: GraphToolAdapter(),
            RouteHint.VECTOR: VectorToolAdapter(),
            RouteHint.COST_RULES: CostRulesToolAdapter(),
        }
    )
    return ApplicationRuntime(
        staging_schema=schema,
        g2_registry=g2_registry,
        semantic_planner=semantic_planner,
        structured_planner=structured_planner,
        structured_executor=structured_executor,
        tool_executor=tool_executor,
        answer_generator=answer_generator or DeterministicAnswerGenerator(),
    )


def get_tool_executor(request: Request) -> ToolExecutor:
    """FastAPI dependency backed by the application-composed runtime."""

    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, ApplicationRuntime):
        raise ApplicationCompositionError("application runtime is not initialized")
    return runtime.tool_executor


def get_answer_generator(request: Request) -> AnswerGenerator:
    """FastAPI dependency for the injected evidence-only generation boundary."""

    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, ApplicationRuntime):
        raise ApplicationCompositionError("application runtime is not initialized")
    return runtime.answer_generator


__all__ = [
    "ApplicationCompositionError",
    "ApplicationRuntime",
    "UnavailableStructuredBackend",
    "build_application_runtime",
    "get_answer_generator",
    "get_tool_executor",
    "load_full_staging_schema",
]
