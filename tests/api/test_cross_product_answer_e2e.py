"""End-to-end GET /answer checks for cross-product COUNT retrieval.

Mirrors the StubBackend/TestClient pattern in tests/api/test_answer_core_e2e.py
so the cross-product wiring is verified against the exact same public
five-string-field contract, HTTP 200 policy, and TOOL_FAILURE/PARTIAL
semantics as the existing single-product endpoint -- which this file does
not modify or re-test.
"""

import json

from fastapi.testclient import TestClient

from app.api.answer_renderer import MAX_THINK_TRACE_CHARS
from app.core.config import Settings
from app.evidence.serializer import MAX_RETRIEVED_CONTEXT_CHARS
from app.main import create_app


ANSWER_FIELDS = {
    "question_id",
    "question",
    "retrieved_context",
    "think_trace",
    "answer",
}


class DispatchBackend:
    """Routes each fetch by staging table name so per-scope counts can
    differ, and can be told to fail for a specific table."""

    def __init__(
        self,
        counts_by_table: dict[str, int],
        *,
        fail_tables: frozenset[str] = frozenset(),
    ) -> None:
        self._counts_by_table = counts_by_table
        self._fail_tables = fail_tables
        self.calls: list[str] = []

    async def fetch_all(self, sql, parameters):
        self.calls.append(sql)
        for table in self._fail_tables:
            if table in sql:
                raise RuntimeError(f"database unavailable for {table}")
        for table, count in self._counts_by_table.items():
            if table in sql:
                return [{"__count": count}]
        raise AssertionError(f"unexpected table in sql: {sql}")


def _client(backend) -> TestClient:
    application = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    )
    return TestClient(application, raise_server_exceptions=False)


def _assert_contract(payload) -> None:
    assert set(payload) == ANSWER_FIELDS
    assert all(isinstance(value, str) for value in payload.values())
    assert len(payload["think_trace"]) <= MAX_THINK_TRACE_CHARS
    assert len(payload["retrieved_context"]) <= MAX_RETRIEVED_CONTEXT_CHARS


def test_two_etf_scopes_count_is_all_supported_e2e() -> None:
    backend = DispatchBackend({"stg_pref01n001": 5, "stg_pref02n001": 9})

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={"question_id": "cp-1", "question": "국내 ETF와 해외 ETF 개수"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    payload = response.json()
    _assert_contract(payload)

    context = json.loads(payload["retrieved_context"])
    assert context["status"] == "SUPPORTED"
    aggregate_by_table = {
        item["source_table"]: item["value"] for item in context["aggregate_evidence"]
    }
    assert aggregate_by_table == {"PREF01N001": 5, "PREF02N001": 9}

    assert "PREF01N001" in payload["think_trace"] or "국내" in payload["think_trace"]
    assert "PREF02N001" in payload["think_trace"] or "해외" in payload["think_trace"]
    assert "5개" in payload["answer"]
    assert "9개" in payload["answer"]


def test_domestic_etf_and_public_fund_count_is_supported_e2e() -> None:
    backend = DispatchBackend({"stg_pref01n001": 3, "stg_prfd01n001": 42})

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={"question_id": "cp-2", "question": "국내 ETF와 공모펀드 개수"},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload)
    context = json.loads(payload["retrieved_context"])
    assert context["status"] == "SUPPORTED"
    aggregate_by_table = {
        item["source_table"]: item["value"] for item in context["aggregate_evidence"]
    }
    assert aggregate_by_table == {"PREF01N001": 3, "PRFD01N001": 42}


def test_one_scope_tool_failure_yields_partial_and_preserves_success_e2e() -> None:
    backend = DispatchBackend(
        {"stg_pref01n001": 5, "stg_pref02n001": 9},
        fail_tables=frozenset({"stg_pref02n001"}),
    )

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={"question_id": "cp-3", "question": "국내 ETF와 해외 ETF 개수"},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload)
    context = json.loads(payload["retrieved_context"])
    assert context["status"] == "PARTIAL"
    assert context["aggregate_evidence"] == [
        {
            "condition_ids": [],
            "decision": "SUPPORTED",
            "operation": "COUNT",
            "source_table": "PREF01N001",
            "value": 5,
        }
    ]
    assert "5개" in payload["answer"]


def test_every_scope_tool_failure_yields_tool_failure_with_http_200_e2e() -> None:
    backend = DispatchBackend(
        {},
        fail_tables=frozenset({"stg_pref01n001", "stg_pref02n001"}),
    )

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={"question_id": "cp-4", "question": "국내 ETF와 해외 ETF 개수"},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload)
    assert json.loads(payload["retrieved_context"])["status"] == "TOOL_FAILURE"
    assert "TOOL_FAILURE" in payload["think_trace"]
    assert "시스템 조회 실패" in payload["answer"]


def test_single_product_count_is_unaffected_by_cross_product_wiring_e2e() -> None:
    """Regression guard: an ordinary single-product question must still
    route through the unmodified single-product path, not cross-product."""

    backend = DispatchBackend({"stg_pref01n001": 7})

    with _client(backend) as client:
        response = client.get(
            "/answer",
            params={"question_id": "single", "question": "국내 ETF 개수"},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload)
    context = json.loads(payload["retrieved_context"])
    assert context["status"] == "SUPPORTED"
    assert context["aggregate_evidence"] == [
        {
            "condition_ids": [],
            "decision": "SUPPORTED",
            "operation": "COUNT",
            "source_table": "PREF01N001",
            "value": 7,
        }
    ]
