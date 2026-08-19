"""Closed-shape tests for the deterministic structured query contract."""

import pytest
from pydantic import ValidationError

from app.structured import (
    AggregateFunction,
    StructuredFilter,
    StructuredQueryContract,
    StructuredSort,
)


def test_row_query_requires_a_projection() -> None:
    with pytest.raises(ValidationError, match="projection"):
        StructuredQueryContract(product_scope="PRBD01N001")


def test_contract_rejects_unknown_operator_before_compilation() -> None:
    with pytest.raises(ValidationError, match="operator"):
        StructuredFilter(field="product_name", operator="DROP", value="x")


@pytest.mark.parametrize(
    "payload",
    [
        {"projections": ("product_name",)},
        {"sort": StructuredSort(field="product_name", direction="ASC")},
        {"limit": 1},
    ],
)
def test_count_rejects_row_only_options(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="COUNT"):
        StructuredQueryContract(
            product_scope="PRBD01N001",
            aggregate=AggregateFunction.COUNT,
            **payload,
        )


def test_contract_rejects_duplicate_projections_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="unique"):
        StructuredQueryContract(
            product_scope="PRBD01N001",
            projections=("product_name", "product_name"),
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        StructuredQueryContract(
            product_scope="PRBD01N001",
            projections=("product_name",),
            sql="DROP TABLE anything",
        )


def test_contract_has_one_typed_sort_and_bounded_top_n() -> None:
    query = StructuredQueryContract(
        product_scope="PRBD01N001",
        projections=("product_name",),
        sort={"field": "aum", "direction": "DESC"},
        limit=10,
    )

    assert query.sort is not None
    assert query.sort.direction.value == "DESC"
    with pytest.raises(ValidationError, match="less than or equal to 100"):
        StructuredQueryContract(
            product_scope="PRBD01N001",
            projections=("product_name",),
            limit=101,
        )
