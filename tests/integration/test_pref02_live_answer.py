"""Read-only PREF02 answer validation against an already loaded staging DB.

Set ``G2B_TEST_DATABASE_URL`` or ``DATABASE_URL`` to opt in.  This test never
creates, changes, or removes database objects.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


LIVE_DATABASE_URL = os.getenv("G2B_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@pytest.mark.skipif(
    not LIVE_DATABASE_URL,
    reason="G2B_TEST_DATABASE_URL/DATABASE_URL is not configured",
)
def test_pref02_aum_top_n_answer_uses_live_multi_projection() -> None:
    application = create_app(
        settings=Settings(_env_file=None, database_url=LIVE_DATABASE_URL),
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        first = client.get(
            "/answer",
            params={
                "question_id": "pref02-live-1",
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
            },
        )
        second = client.get(
            "/answer",
            params={
                "question_id": "pref02-live-2",
                "question": "해외 ETF 중 AUM이 큰 상품 3개",
            },
        )

    assert first.status_code == second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    first_context = json.loads(first_payload["retrieved_context"])
    second_context = json.loads(second_payload["retrieved_context"])
    assert first_context == second_context
    assert first_context["status"] == "SUPPORTED"
    evidence = first_context["evidence"]
    assert len(evidence) == first_context["evidence_count"] == 9
    assert {item["source_table"] for item in evidence} == {"PREF02N001"}
    assert {item["source_field"] for item in evidence} == {
        "pd_itm_no#1",
        "pd_nm#1",
        "du_last_aum#1",
    }

    rows: dict[str, dict[str, object]] = {}
    for item in evidence:
        rows.setdefault(item["source_row_id"], {})[item["source_field"]] = item
    assert len(rows) == 3
    aum_values: list[Decimal] = []
    for row in rows.values():
        identifier = row["pd_itm_no#1"]["normalized_value"]
        assert isinstance(identifier, str) and identifier
        assert {item["product_key"] for item in row.values()} == {identifier}
        name = row["pd_nm#1"]["normalized_value"]
        assert isinstance(name, str) and name
        aum_values.append(Decimal(row["du_last_aum#1"]["normalized_value"]))
    assert aum_values == sorted(aum_values, reverse=True)
    assert "source-native 값" in first_payload["answer"]
