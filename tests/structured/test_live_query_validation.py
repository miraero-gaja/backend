"""Unit tests for the G2-B live query validation shape logic.

The production execution machinery (``StructuredQueryCompiler``,
``StructuredQueryExecutor``, ``PsycopgQueryBackend``, and Evidence
conversion) is already exhaustively covered by
``tests/structured/test_query_compiler.py`` and
``tests/structured/test_query_executor.py``. Re-simulating a full SQL engine
here would duplicate that coverage without testing anything new.

What *is* new and worth testing directly is ``live_validation.py``'s own
logic: which fields it probes, how it seeds real-looking values through a
small read-only oracle, and -- most importantly -- whether a genuine mismatch
between the production path and the independent oracle is actually reported
as FAIL rather than silently swallowed into PASS.

So these tests:
  * monkeypatch ``_run_production`` to return controlled, realistic
    ``StructuredExecutionResult`` objects built from the *real* result/
    evidence classes (no fakes of those), keyed off the shape of the
    contract that was passed in; and
  * exercise the independent oracle against a tiny in-memory table using the
    module's own (deliberately simple, AND-only) WHERE/ORDER BY/LIMIT/GROUP
    BY grammar.

A separate, opt-in integration test
(``tests/integration/test_g2b_live_query_validation.py``) exercises the real
production path against a real, already-loaded PostgreSQL database when
``DATABASE_URL`` and network access are available.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.evidence.models import EvidenceItem, SupportStatus
from app.structured.contracts import AggregateFunction, FilterOperator, SortDirection
from app.structured.executor import StructuredExecutionResult
from app.structured.registry import TrustedField, TrustedQueryRegistry, TrustedTable
from pipeline.structured import live_validation
from pipeline.structured.live_validation import LiveQueryValidationError, run_live_query_validation
from pipeline.normalize.models import TargetType


# --- a tiny in-memory table used only by the independent oracle ------------


_TERM = re.compile(r'"(?P<col>\w+)"\s*(?P<op>=|>=|IS NOT NULL|IS NULL)')


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._result: list[tuple] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._result = _run(sql, params, self._rows)

    def fetchall(self):
        return self._result


class FakeConnection:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._rows)

    def close(self) -> None:
        self.closed = True


def _eval_where(where: str, row: dict, params: tuple) -> bool:
    if not where.strip():
        return True
    params_iter = iter(params)
    ok = True
    for match in _TERM.finditer(where):
        col, op = match.group("col"), match.group("op")
        value = row.get(col)
        if op == "IS NULL":
            ok = ok and value is None
        elif op == "IS NOT NULL":
            ok = ok and value is not None
        elif op == "=":
            ok = ok and value == next(params_iter)
        elif op == ">=":
            ok = ok and value is not None and Decimal(str(value)) >= Decimal(str(next(params_iter)))
    return ok


def _run(sql: str, params: tuple, rows: list[dict]) -> list[tuple]:
    lowered = sql.lower()
    where_match = re.search(r"where\s+(.*?)(?:group by|order by|limit|$)", lowered, re.DOTALL)
    where = sql[where_match.start(1) : where_match.end(1)] if where_match else ""
    filtered = [row for row in rows if _eval_where(where, row, params)]

    group_match = re.search(r'group by\s+"(\w+)"', lowered)
    if group_match:
        group_col = group_match.group(1)
        counts: dict = {}
        for row in filtered:
            counts[row[group_col]] = counts.get(row[group_col], 0) + 1
        if not counts:
            return []
        ordered = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
        return [ordered[0]]

    if "count(*)" in lowered and "group by" not in lowered:
        return [(len(filtered),)]

    if "min(" in lowered:
        values = [row[col] for row in rows for col in [re.search(r'min\("(\w+)"\)', lowered).group(1)] if row.get(col) is not None]
        return [(min(values, key=lambda v: Decimal(str(v))),)] if values else [(None,)]

    order_match = re.search(r'order by\s+"(\w+)"\s+(asc|desc)', lowered)
    if order_match:
        col, direction = order_match.group(1), order_match.group(2)

        def _sort_key(row: dict) -> Decimal:
            value = row[col]
            return Decimal(str(value)) if isinstance(value, Decimal) else Decimal(0)

        filtered = sorted(filtered, key=_sort_key, reverse=(direction == "desc"))
        filtered.sort(key=lambda row: row[col] is None)  # NULLS LAST always, stable sort

    limit_match = re.search(r"limit\s+(\d+)", lowered)
    if limit_match:
        filtered = filtered[: int(limit_match.group(1))]

    select_cols = re.match(r"select\s+(.*?)\s+from", lowered, re.DOTALL).group(1)
    projected = [m.group(1) for m in re.finditer(r'"(\w+)"', select_cols)]
    return [tuple(row.get(col) for col in projected) for row in filtered]


def _rows(count: int = 20) -> list[dict]:
    data = []
    for i in range(count):
        data.append(
            {
                "source_row_id": f"srid:v1:{i:03d}",
                "c001_pd_itm_no": f"CODE{i:03d}",
                "c002_pd_exg_mkt_cd": "KRX" if i % 3 else "NXT",
                "c003_pd_lst_stk_cnt": None if i == 5 else Decimal(i * 100),
            }
        )
    return data


def _registry() -> TrustedQueryRegistry:
    table = TrustedTable("PREF01N001", "structured_staging", "stg_pref01n001")
    fields = [
        TrustedField(
            semantic_key="pref01.product_code",
            logical_table_id="PREF01N001",
            source_column="pd_itm_no",
            qualified_name="pd_itm_no#1",
            physical_column="c001_pd_itm_no",
            target_type=TargetType.TEXT,
            allowed_operations=frozenset({"EQ", "NE"}),
        ),
        TrustedField(
            semantic_key="pref01.exchange_code",
            logical_table_id="PREF01N001",
            source_column="pd_exg_mkt_cd",
            qualified_name="pd_exg_mkt_cd#1",
            physical_column="c002_pd_exg_mkt_cd",
            target_type=TargetType.TEXT,
            allowed_operations=frozenset({"EQ", "NE"}),
        ),
        TrustedField(
            semantic_key="pref01.listed_share_count",
            logical_table_id="PREF01N001",
            source_column="pd_lst_stk_cnt",
            qualified_name="pd_lst_stk_cnt#1",
            physical_column="c003_pd_lst_stk_cnt",
            target_type=TargetType.DECIMAL,
            allowed_operations=frozenset({"EQ", "NE", "LT", "LE", "GT", "GE", "SORT"}),
        ),
    ]
    return TrustedQueryRegistry((table,), fields)


def _evidence(row: dict, field_key: str, qualified_name: str, decision: SupportStatus = SupportStatus.SUPPORTED) -> EvidenceItem:
    value = row.get(f"c00{'1' if field_key.endswith('product_code') else '2' if field_key.endswith('exchange_code') else '3'}_" + {
        "pref01.product_code": "pd_itm_no",
        "pref01.exchange_code": "pd_exg_mkt_cd",
        "pref01.listed_share_count": "pd_lst_stk_cnt",
    }[field_key])
    return EvidenceItem(
        product_key=row["source_row_id"],
        source_table="PREF01N001",
        source_row_id=row["source_row_id"],
        source_field=qualified_name,
        raw_value=str(value) if value is not None else None,
        normalized_value=value if decision is SupportStatus.SUPPORTED else None,
        decision=decision,
    )


def _result(candidates, evidence, columns=()) -> StructuredExecutionResult:
    return StructuredExecutionResult(
        query_fingerprint="fingerprint",
        candidates=tuple(candidates),
        columns=tuple(columns),
        evidence=tuple(evidence),
        compiled_query=None,  # not used by any live_validation check
    )


def _consistent_fake_production(rows: list[dict]):
    """A production-path stub whose answers always agree with ``rows``."""

    by_code = {row["c001_pd_itm_no"]: row for row in rows}

    def fake(_registry, _connection_factory, query):
        if query.aggregate is AggregateFunction.COUNT:
            value = query.filters[0].value
            count = sum(1 for row in rows if row["c002_pd_exg_mkt_cd"] == value)
            return _result([{"count": count}], [])

        if len(query.filters) == 2:
            row = next(
                r
                for r in rows
                if r["c001_pd_itm_no"] == query.filters[0].value
                and r["c002_pd_exg_mkt_cd"] == query.filters[1].value
            )
            candidate = {"pref01.product_code": row["c001_pd_itm_no"], "pref01.exchange_code": row["c002_pd_exg_mkt_cd"]}
            evidence = [
                _evidence(row, "pref01.product_code", "pd_itm_no#1"),
                _evidence(row, "pref01.exchange_code", "pd_exg_mkt_cd#1"),
            ]
            return _result([candidate], evidence)

        if query.filters and query.filters[0].field == "pref01.product_code" and query.filters[0].operator is FilterOperator.EQ:
            projections = query.projections
            row = by_code[query.filters[0].value]
            candidate = {}
            evidence = []
            for key in projections:
                qualified = {
                    "pref01.product_code": "pd_itm_no#1",
                    "pref01.listed_share_count": "pd_lst_stk_cnt#1",
                }[key]
                column = {
                    "pref01.product_code": "c001_pd_itm_no",
                    "pref01.listed_share_count": "c003_pd_lst_stk_cnt",
                }[key]
                value = row[column]
                candidate[key] = value
                decision = SupportStatus.UNSUPPORTED if value is None else SupportStatus.SUPPORTED
                evidence.append(_evidence(row, key, qualified, decision))
            return _result([candidate], evidence)

        if query.filters and query.filters[0].operator is FilterOperator.GE:
            threshold = query.filters[0].value
            matches = [r for r in rows if r["c003_pd_lst_stk_cnt"] is not None and r["c003_pd_lst_stk_cnt"] >= threshold]
            matches = matches[: query.limit or len(matches)]
            candidates = [{"pref01.listed_share_count": r["c003_pd_lst_stk_cnt"]} for r in matches]
            evidence = [_evidence(r, "pref01.listed_share_count", "pd_lst_stk_cnt#1") for r in matches]
            return _result(candidates, evidence)

        if query.sort is not None:
            direction = query.sort.direction
            candidates_rows = sorted(
                (r for r in rows if r["c003_pd_lst_stk_cnt"] is not None),
                key=lambda r: r["c003_pd_lst_stk_cnt"],
                reverse=(direction is SortDirection.DESC),
            )
            candidates_rows = candidates_rows[: query.limit or len(candidates_rows)]
            candidates = [{"pref01.listed_share_count": r["c003_pd_lst_stk_cnt"]} for r in candidates_rows]
            evidence = [_evidence(r, "pref01.listed_share_count", "pd_lst_stk_cnt#1") for r in candidates_rows]
            return _result(candidates, evidence)

        raise AssertionError(f"unexpected contract in fake production stub: {query!r}")

    return fake


def test_all_seven_shapes_plus_parse_status_gate_pass_against_a_consistent_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _rows()
    monkeypatch.setattr(live_validation, "_run_production", _consistent_fake_production(rows))

    result = run_live_query_validation(lambda: FakeConnection(rows), _registry())

    assert result["status"] == "PASS"
    assert set(result["shapes"]) == {
        "eq",
        "range",
        "multi_filter",
        "sort_asc",
        "sort_desc",
        "top_n",
        "count",
    }
    assert all(shape["status"] == "PASS" for shape in result["shapes"].values())
    assert result["parse_status_gate"]["status"] == "PASS"
    assert result["query_values_copied_to_report"] is False


def test_count_mismatch_between_production_and_oracle_is_reported_as_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _rows()

    def lying_production(_registry, _connection_factory, query):
        if query.aggregate is AggregateFunction.COUNT:
            # Deliberately wrong: off by one from what the independent
            # oracle will compute, to prove a real mismatch is caught.
            value = query.filters[0].value
            real_count = sum(1 for row in rows if row["c002_pd_exg_mkt_cd"] == value)
            return _result([{"count": real_count + 1}], [])
        return _consistent_fake_production(rows)(_registry, _connection_factory, query)

    monkeypatch.setattr(live_validation, "_run_production", lying_production)

    result = run_live_query_validation(lambda: FakeConnection(rows), _registry())

    assert result["status"] == "FAIL"
    assert result["shapes"]["count"]["status"] == "FAIL"
    assert result["shapes"]["count"]["checks"]["aggregate_value_matches_independent_oracle"] is False
    # Every other, unrelated shape must still be evaluated and unaffected.
    assert result["shapes"]["eq"]["status"] == "PASS"


def test_sort_order_mismatch_is_reported_as_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _rows()

    def scrambled_production(_registry, _connection_factory, query):
        if query.sort is not None and query.limit == live_validation._ROW_LIMIT:
            # Return the right rows but in the wrong order.
            candidates_rows = sorted(
                (r for r in rows if r["c003_pd_lst_stk_cnt"] is not None),
                key=lambda r: r["source_row_id"],
            )[: query.limit]
            candidates = [{"pref01.listed_share_count": r["c003_pd_lst_stk_cnt"]} for r in candidates_rows]
            evidence = [_evidence(r, "pref01.listed_share_count", "pd_lst_stk_cnt#1") for r in candidates_rows]
            return _result(candidates, evidence)
        return _consistent_fake_production(rows)(_registry, _connection_factory, query)

    monkeypatch.setattr(live_validation, "_run_production", scrambled_production)

    result = run_live_query_validation(lambda: FakeConnection(rows), _registry())

    assert result["status"] == "FAIL"
    assert result["shapes"]["sort_asc"]["status"] == "FAIL" or result["shapes"]["sort_desc"]["status"] == "FAIL"


def test_refuses_a_whitespace_conflicted_probe_field() -> None:
    table = TrustedTable("PREF01N001", "structured_staging", "stg_pref01n001")
    conflicted_field = TrustedField(
        semantic_key="pref01.product_code",
        logical_table_id="PREF01N001",
        source_column="pd_mkt_nm",
        qualified_name="pd_mkt_nm#1",
        physical_column="c001_pd_mkt_nm",
        target_type=TargetType.TEXT,
        allowed_operations=frozenset({"EQ", "NE"}),
    )
    registry = TrustedQueryRegistry((table,), (conflicted_field,))

    with pytest.raises(LiveQueryValidationError, match="whitespace-conflicted"):
        run_live_query_validation(lambda: FakeConnection([]), registry)


def test_parse_status_gate_is_not_applicable_when_no_null_row_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [row for row in _rows() if row["c003_pd_lst_stk_cnt"] is not None]
    monkeypatch.setattr(live_validation, "_run_production", _consistent_fake_production(rows))

    result = run_live_query_validation(lambda: FakeConnection(rows), _registry())

    assert result["parse_status_gate"]["status"] == "NOT_APPLICABLE"
    # NOT_APPLICABLE must never silently count as an overall FAIL.
    assert result["status"] == "PASS"
