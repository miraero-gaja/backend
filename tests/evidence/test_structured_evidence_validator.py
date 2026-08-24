"""Structured retrieval evidence competency checks."""

import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from app.agent import QueryContract, RouteHint, ToolResult
from app.agent.grounder import OntologyGrounder
from app.agent.parser import QueryParser
from app.agent.router import QueryRouter
from app.core.config import Settings
from app.core.deadline import Deadline
from app.evidence.models import EvidenceItem, ReasonCode, SupportStatus
from app.evidence.validator import (
    EvidenceValidator,
    StructuredEvidenceValidationError,
    StructuredEvidenceValidator,
)
from app.main import create_app


class RecordingBackend:
    def __init__(self, rows=(), error: Exception | None = None) -> None:
        self.rows = tuple(rows)
        self.error = error
        self.calls = []

    async def fetch_all(self, sql, parameters):
        self.calls.append((sql, tuple(parameters)))
        if self.error is not None:
            raise self.error
        return self.rows


def _aum_row(index: int, value: str, *, source_id: bool = True):
    row = {
        "__logical_table_id": "PREF02N001",
        "__raw_record": {
            "pd_itm_no#1": {"type": "STRING", "value": f"ETF{index:03d}"},
            "pd_nm#1": {"type": "STRING", "value": f"해외 ETF {index}"},
            "du_last_aum#1": {"type": "DECIMAL", "value": value},
        },
        "__parse_statuses": {
            "pd_itm_no#1": "OK",
            "pd_nm#1": "OK",
            "du_last_aum#1": "OK",
        },
        "__value_000": f"ETF{index:03d}",
        "__value_001": f"해외 ETF {index}",
        "__value_002": Decimal(value),
    }
    if source_id:
        row["__source_row_id"] = f"srid:v1:aum-{index:03d}"
    return row


def _product_code_row(value: str):
    return {
        "__source_row_id": "srid:v1:pref01-code",
        "__logical_table_id": "PREF01N001",
        "__raw_record": {
            "pd_itm_no#1": {"type": "STRING", "value": value}
        },
        "__parse_statuses": {"pd_itm_no#1": "OK"},
        "__value_000": value,
    }


def _ground(question: str):
    parsed = QueryParser().parse(
        request_id="evidence-validator-request",
        question_id="evidence-validator-question",
        question=question,
    )
    return OntologyGrounder().ground(parsed)


def _execute(question: str, backend: RecordingBackend):
    application = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    )
    query = _ground(question)
    route = QueryRouter().route(query)
    results = asyncio.run(
        application.state.runtime.tool_executor.execute(
            query,
            route,
            Deadline.after(2),
        )
    )
    evidence = tuple(item for result in results for item in result.evidence)
    decision = EvidenceValidator().validate(query, results, evidence)
    return query, results, decision


def test_aum_desc_top_three_creates_supported_evidence() -> None:
    backend = RecordingBackend(
        _aum_row(index, value)
        for index, value in enumerate(("30", "20", "10"), start=1)
    )

    query, results, decision = _execute(
        "해외 ETF 중 AUM이 큰 상품 3개",
        backend,
    )

    assert query.route_hint is RouteHint.STRUCTURED
    assert len(backend.calls) == 1
    assert decision.status is SupportStatus.SUPPORTED
    assert decision.reason_codes == ()
    assert len(decision.evidence) == 9
    assert tuple(
        item.normalized_value
        for item in decision.evidence
        if item.source_field == "du_last_aum#1"
    ) == ("30", "20", "10")
    assert {item.product_key for item in decision.evidence} == {
        "ETF001",
        "ETF002",
        "ETF003",
    }
    assert all(item.source_table == "PREF02N001" for item in decision.evidence)
    assert {item.source_field for item in decision.evidence} == {
        "pd_itm_no#1",
        "pd_nm#1",
        "du_last_aum#1",
    }
    assert all(item.unit is None for item in decision.evidence)
    assert all(item.snapshot is None for item in decision.evidence)
    assert results[0].validation_trace[-3:] == (
        "3건 반환",
        "Top-N 검증: 3",
        "Evidence 확정",
    )


def test_normal_zero_rows_is_no_match_not_tool_failure() -> None:
    backend = RecordingBackend()

    _query, results, decision = _execute(
        "해외 ETF 중 AUM이 큰 상품 3개",
        backend,
    )

    assert len(backend.calls) == 1
    assert results[0].error_code is ReasonCode.NO_MATCH
    assert decision.status is SupportStatus.NO_MATCH
    assert decision.reason_codes == (ReasonCode.NO_MATCH,)
    assert decision.evidence == ()
    assert "NO_MATCH 확정" in decision.summary


def test_g3_result_without_semantic_gate_trace_is_rejected() -> None:
    backend = RecordingBackend((_aum_row(1, "30"),))
    application = create_app(
        settings=Settings(_env_file=None, database_url=None),
        structured_backend=backend,
    )
    query = _ground("해외 ETF 중 AUM이 큰 상품 3개")
    assert query.structured_query is not None
    result = asyncio.run(
        application.state.runtime.structured_executor.execute(
            query.structured_query
        )
    )

    with pytest.raises(
        StructuredEvidenceValidationError,
        match="semantic gate approval trace",
    ):
        StructuredEvidenceValidator().validate(
            query.structured_query,
            replace(result, semantic_gate_trace=()),
        )


def test_closed_operation_is_unsupported_without_backend_execution() -> None:
    backend = RecordingBackend()

    query, results, decision = _execute(
        "해외 ETF 총보수 0.5% 이하",
        backend,
    )

    assert query.route_hint is RouteHint.UNSUPPORTED
    assert results == ()
    assert backend.calls == []
    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.reason_codes == (ReasonCode.FIELD_NOT_AVAILABLE,)


def test_backend_exception_is_tool_failure_not_no_match() -> None:
    backend = RecordingBackend(error=RuntimeError("database unavailable"))

    _query, results, decision = _execute(
        "해외 ETF 중 AUM이 큰 상품 3개",
        backend,
    )

    assert len(backend.calls) == 1
    assert results[0].error_code is ReasonCode.TOOL_FAILURE
    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.reason_codes == (ReasonCode.TOOL_FAILURE,)
    assert ReasonCode.NO_MATCH not in decision.reason_codes


@pytest.mark.parametrize(
    "rows",
    (
        (
            _aum_row(1, "20"),
            _aum_row(2, "30"),
            _aum_row(3, "10"),
        ),
        (
            _aum_row(1, "40"),
            _aum_row(2, "30"),
            _aum_row(3, "20"),
            _aum_row(4, "10"),
        ),
    ),
)
def test_sort_or_limit_violation_cannot_be_supported(rows) -> None:
    backend = RecordingBackend(rows)

    _query, results, decision = _execute(
        "해외 ETF 중 AUM이 큰 상품 3개",
        backend,
    )

    assert results[0].error_code is ReasonCode.TOOL_FAILURE
    assert results[0].evidence == ()
    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.reason_codes == (ReasonCode.TOOL_FAILURE,)


def test_missing_source_identity_cannot_be_supported() -> None:
    backend = RecordingBackend((_aum_row(1, "30", source_id=False),))

    _query, results, decision = _execute(
        "해외 ETF 중 AUM이 큰 상품 3개",
        backend,
    )

    assert results[0].error_code is ReasonCode.TOOL_FAILURE
    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.evidence == ()


def test_missing_projected_product_name_provenance_cannot_be_supported() -> None:
    row = _aum_row(1, "30")
    del row["__raw_record"]["pd_nm#1"]
    backend = RecordingBackend((row,))

    _query, results, decision = _execute(
        "해외 ETF 중 AUM이 큰 상품 3개",
        backend,
    )

    assert results[0].error_code is ReasonCode.TOOL_FAILURE
    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.evidence == ()


def test_g2_product_code_eq_generates_condition_evidence() -> None:
    backend = RecordingBackend((_product_code_row("069500"),))

    _query, _results, decision = _execute(
        "국내 ETF 중 상품코드가 069500인 상품",
        backend,
    )

    assert decision.status is SupportStatus.SUPPORTED
    assert len(decision.evidence) == 1
    item = decision.evidence[0]
    assert item.source_table == "PREF01N001"
    assert item.source_field == "pd_itm_no#1"
    assert item.raw_value == "069500"
    assert item.normalized_value == "069500"
    assert item.condition_id == "filter_1"
    assert item.decision is SupportStatus.SUPPORTED


def test_returned_value_that_violates_filter_is_tool_failure() -> None:
    backend = RecordingBackend((_product_code_row("999999"),))

    _query, results, decision = _execute(
        "국내 ETF 중 상품코드가 069500인 상품",
        backend,
    )

    assert results[0].error_code is ReasonCode.TOOL_FAILURE
    assert decision.status is SupportStatus.UNSUPPORTED
    assert decision.reason_codes == (ReasonCode.TOOL_FAILURE,)


def test_mixed_verifiable_facts_are_partial_not_supported() -> None:
    supported = EvidenceItem(
        product_key="row-1",
        source_table="PREF01N001",
        source_row_id="row-1",
        source_field="pd_itm_no#1",
        raw_value="069500",
        normalized_value="069500",
        decision=SupportStatus.SUPPORTED,
    )
    unsupported = supported.model_copy(
        update={
            "source_field": "pd_nm#1",
            "raw_value": None,
            "normalized_value": None,
            "decision": SupportStatus.UNSUPPORTED,
        }
    )
    query = QueryContract(request_id="r", question_id="q")
    result = ToolResult(
        tool_name="mixed-evidence-test",
        query_fingerprint="fingerprint",
        candidates=({"pref01.product_code": "069500"},),
        evidence=(supported, unsupported),
        validation_trace=("일부 evidence 검증",),
    )

    decision = EvidenceValidator().validate(query, (result,), result.evidence)

    assert decision.status is SupportStatus.PARTIAL
    assert decision.reason_codes == (ReasonCode.FIELD_NOT_AVAILABLE,)
