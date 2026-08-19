"""Opt-in live PostgreSQL check for the parameterized structured path.

Set ``G2B_TEST_DATABASE_URL`` to a disposable test database.  The test creates
only a session-local temporary table and closes the session after the query.
It deliberately does not fall back to the application's ``DATABASE_URL`` so a
normal test run cannot modify an operator's staging database.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.structured import (
    PsycopgQueryBackend,
    StructuredFilter,
    StructuredQueryCompiler,
    StructuredQueryContract,
    StructuredQueryExecutor,
    TrustedField,
    TrustedQueryRegistry,
    TrustedTable,
)
from pipeline.normalize.models import TargetType


TEST_DATABASE_URL = os.getenv("G2B_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="G2B_TEST_DATABASE_URL is not configured for a disposable database",
)
def test_live_postgres_structured_query_and_lineage() -> None:
    import psycopg

    connection = psycopg.connect(TEST_DATABASE_URL, connect_timeout=5)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TEMPORARY TABLE g2b_query_test (
                    source_row_id text PRIMARY KEY,
                    logical_table_id text NOT NULL,
                    raw_record jsonb NOT NULL,
                    parse_statuses jsonb NOT NULL,
                    c001_product_name text
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO g2b_query_test (
                    source_row_id, logical_table_id, raw_record, parse_statuses,
                    c001_product_name
                ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    "srid:v1:live-test",
                    "TEST01",
                    '{"PRODUCT_NAME#1":{"type":"STRING","value":"exact raw"}}',
                    '{"PRODUCT_NAME#1":"OK"}',
                    "exact raw",
                ),
            )
        connection.commit()

        registry = TrustedQueryRegistry(
            (TrustedTable("TEST01", "pg_temp", "g2b_query_test"),),
            (
                TrustedField(
                    semantic_key="product_name",
                    logical_table_id="TEST01",
                    source_column="PRODUCT_NAME",
                    qualified_name="PRODUCT_NAME#1",
                    physical_column="c001_product_name",
                    target_type=TargetType.TEXT,
                    allowed_operations=frozenset({"EQ", "NE"}),
                ),
            ),
        )
        executor = StructuredQueryExecutor(
            StructuredQueryCompiler(registry),
            PsycopgQueryBackend(lambda: connection),
        )
        result = asyncio.run(
            executor.execute(
                StructuredQueryContract(
                    product_scope="TEST01",
                    filters=(
                        StructuredFilter(
                            field="product_name", operator="EQ", value="exact raw"
                        ),
                    ),
                    projections=("product_name",),
                )
            )
        )

        assert result.candidates == ({"product_name": "exact raw"},)
        assert len(result.evidence) == 1
        assert result.evidence[0].source_row_id == "srid:v1:live-test"
        assert result.evidence[0].source_field == "PRODUCT_NAME#1"
        assert result.evidence[0].raw_value == "exact raw"
        assert result.evidence[0].normalized_value == "exact raw"
    finally:
        if not connection.closed:
            connection.close()
