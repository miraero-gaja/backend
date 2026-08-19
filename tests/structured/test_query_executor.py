"""Execution, evidence, psycopg facade, and adapter behavior tests."""

import asyncio
from decimal import Decimal

from app.agent.contracts import QueryContract, RouteHint
from app.core.deadline import Deadline
from app.evidence.models import ReasonCode, SupportStatus
from app.structured import (
    AggregateFunction,
    PsycopgQueryBackend,
    StructuredFilter,
    StructuredQueryCompiler,
    StructuredQueryContract,
    StructuredQueryExecutor,
    TrustedField,
    TrustedQueryRegistry,
    TrustedTable,
)
from app.tools.structured import StructuredToolAdapter
from pipeline.normalize.models import TargetType


def _compiler() -> StructuredQueryCompiler:
    return StructuredQueryCompiler(
        TrustedQueryRegistry(
            [TrustedTable("PRBD01N001", "structured_staging", "stg_prbd01n001")],
            [
                TrustedField(
                    semantic_key="product_name",
                    logical_table_id="PRBD01N001",
                    source_column="PD_NM",
                    qualified_name="PD_NM#1",
                    physical_column="c002_pd_nm",
                    target_type=TargetType.TEXT,
                    allowed_operations=frozenset({"EQ", "NE"}),
                ),
                TrustedField(
                    semantic_key="aum",
                    logical_table_id="PRBD01N001",
                    source_column="AUM",
                    qualified_name="AUM#1",
                    physical_column="c010_aum",
                    target_type=TargetType.DECIMAL,
                    allowed_operations=frozenset(
                        {"EQ", "NE", "LT", "LE", "GT", "GE", "SORT"}
                    ),
                ),
            ],
        )
    )


class FakeBackend:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        return self.rows


def test_executor_returns_candidates_and_raw_typed_lineage_evidence() -> None:
    raw_name = " Alpha  "
    backend = FakeBackend(
        [
            {
                "__source_row_id": "srid:v1:abc",
                "__logical_table_id": "PRBD01N001",
                "__raw_record": {
                    "PD_NM#1": {"type": "STRING", "value": raw_name},
                    "AUM#1": {"type": "DECIMAL", "value": "10.50"},
                },
                "__parse_statuses": {"PD_NM#1": "OK", "AUM#1": "OK"},
                "__value_000": raw_name,
                "__value_001": Decimal("10.50"),
            }
        ]
    )
    executor = StructuredQueryExecutor(_compiler(), backend)
    result = asyncio.run(
        executor.execute(
            StructuredQueryContract(
                product_scope="PRBD01N001",
                filters=(StructuredFilter(field="aum", operator="GE", value="10"),),
                projections=("product_name",),
            )
        )
    )

    assert result.candidates == ({"product_name": raw_name},)
    assert result.columns == ("product_name",)
    assert len(result.evidence) == 2
    name, aum = result.evidence
    assert name.source_row_id == "srid:v1:abc"
    assert name.source_table == "PRBD01N001"
    assert name.source_field == "PD_NM#1"
    assert name.raw_value == raw_name
    assert name.normalized_value == raw_name
    assert name.decision is SupportStatus.SUPPORTED
    assert aum.source_field == "AUM#1"
    assert aum.raw_value == "10.50"
    assert aum.normalized_value == "10.50"
    assert aum.condition_id == "filter_1"


def test_non_ok_parse_state_cannot_become_supported_evidence() -> None:
    backend = FakeBackend(
        [
            {
                "__source_row_id": "srid:v1:missing",
                "__logical_table_id": "PRBD01N001",
                "__raw_record": {"PD_NM#1": {"type": "NULL", "value": None}},
                "__parse_statuses": {"PD_NM#1": "MISSING"},
                "__value_000": None,
            }
        ]
    )
    result = asyncio.run(
        StructuredQueryExecutor(_compiler(), backend).execute(
            StructuredQueryContract(
                product_scope="PRBD01N001",
                projections=("product_name",),
            )
        )
    )

    assert result.candidates == ({"product_name": None},)
    assert len(result.evidence) == 1
    assert result.evidence[0].raw_value is None
    assert result.evidence[0].normalized_value is None
    assert result.evidence[0].decision is SupportStatus.UNSUPPORTED


def test_count_zero_is_a_valid_deterministic_result_without_fake_row_evidence() -> None:
    backend = FakeBackend([{"__count": 0}])
    result = asyncio.run(
        StructuredQueryExecutor(_compiler(), backend).execute(
            StructuredQueryContract(
                product_scope="PRBD01N001",
                aggregate=AggregateFunction.COUNT,
            )
        )
    )

    assert result.candidates == ({"count": 0},)
    assert result.evidence == ()


class FakeDescription:
    def __init__(self, name):
        self.name = name

    def __getitem__(self, index):
        return (self.name,)[index]


class FakeCursor:
    description = (FakeDescription("value"),)

    def __init__(self):
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql, parameters):
        self.executed = (sql, parameters)

    def fetchall(self):
        return [(Decimal("1.25"),)]


class FakeConnection:
    def __init__(self):
        self.cursor_value = FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def close(self):
        self.closed = True


def test_psycopg_backend_passes_sql_and_parameters_separately_and_closes() -> None:
    connection = FakeConnection()
    backend = PsycopgQueryBackend(lambda: connection)
    rows = asyncio.run(backend.fetch_all("SELECT %s AS value", (Decimal("1.25"),)))

    assert rows == ({"value": Decimal("1.25")},)
    assert connection.cursor_value.executed == (
        "SELECT %s AS value",
        (Decimal("1.25"),),
    )
    assert connection.closed is True


def test_tool_adapter_stays_unavailable_without_explicit_structured_query() -> None:
    generic = QueryContract(
        request_id="request",
        question_id="question",
        route_hint=RouteHint.STRUCTURED,
    )
    unavailable = asyncio.run(
        StructuredToolAdapter().execute(generic, Deadline.after(1))
    )

    assert unavailable.error_code is ReasonCode.TOOL_FAILURE
    assert unavailable.warnings == ("adapter_not_connected",)


def test_tool_adapter_executes_an_explicit_structured_contract_directly() -> None:
    backend = FakeBackend([{"__count": 3}])
    executor = StructuredQueryExecutor(_compiler(), backend)
    adapter = StructuredToolAdapter(executor)
    result = asyncio.run(
        adapter.execute_structured(
            StructuredQueryContract(
                product_scope="PRBD01N001",
                aggregate=AggregateFunction.COUNT,
            ),
            Deadline.after(1),
        )
    )

    assert result.candidates == ({"count": 3},)
    assert result.columns == ("count",)


def test_tool_adapter_reads_the_plan_from_the_generic_contract() -> None:
    backend = FakeBackend([{"__count": 3}])
    adapter = StructuredToolAdapter(StructuredQueryExecutor(_compiler(), backend))
    generic = QueryContract(
        request_id="request",
        question_id="question",
        structured_query=StructuredQueryContract(
            product_scope="PRBD01N001",
            aggregate=AggregateFunction.COUNT,
        ),
    )

    result = asyncio.run(adapter.execute(generic, Deadline.after(1)))

    assert result.candidates == ({"count": 3},)
    assert result.columns == ("count",)
    assert result.evidence == ()
