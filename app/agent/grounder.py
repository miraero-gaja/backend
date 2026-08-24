"""Registry-backed grounding from deterministic parsing to structured plans."""

from __future__ import annotations

from app.agent.contracts import (
    QueryContract,
    QueryUnderstandingStatus,
    RouteHint,
)
from app.structured.contracts import (
    AggregateFunction,
    StructuredFilter,
    StructuredQueryContract,
    StructuredSort,
)
from mappings.core import CoreUnitStatus, get_confirmed_field_map
from mappings.semantic import (
    ClaimStatus,
    get_default_projection_keys,
    get_semantic_field_approval,
)


def _unsupported(query: QueryContract, reason: str, trace: list[str]) -> QueryContract:
    understanding = query.understanding
    assert understanding is not None
    return query.model_copy(
        update={
            "ambiguity": (),
            "route_hint": RouteHint.UNSUPPORTED,
            "structured_query": None,
            "understanding": understanding.model_copy(
                update={
                    "status": QueryUnderstandingStatus.UNSUPPORTED,
                    "unsupported_reason": reason,
                    "execution_trace": tuple(trace),
                }
            ),
        }
    )


class OntologyGrounder:
    """Approve parsed operations through G2 plus the separate G3 safety layer."""

    def ground(self, query: QueryContract) -> QueryContract:
        # Preserve the established G2 caller contract for already-built plans.
        if query.understanding is None:
            if (
                query.structured_query is not None
                and not query.required_inputs
                and not query.ambiguity
            ):
                return query.model_copy(update={"route_hint": RouteHint.STRUCTURED})
            return query.model_copy(update={"route_hint": RouteHint.UNSUPPORTED})

        understanding = query.understanding
        if understanding.status is not QueryUnderstandingStatus.PARSED:
            return query.model_copy(update={"route_hint": RouteHint.UNSUPPORTED})

        table = understanding.logical_table_id
        if table is None:
            return _unsupported(
                query,
                "product_scope_missing",
                [*understanding.execution_trace, "상품군 승인: 실패"],
            )

        trace = list(understanding.execution_trace)
        if understanding.aggregate is AggregateFunction.COUNT:
            if (
                understanding.semantic_keys
                or understanding.filter_conditions
                or understanding.sort_direction is not None
                or understanding.limit is not None
            ):
                return _unsupported(
                    query,
                    "filtered_aggregation_not_supported",
                    [*trace, "집계 조합 승인: 실패"],
                )
            plan = StructuredQueryContract(
                product_scope=table,
                aggregate=AggregateFunction.COUNT,
            )
            trace.append("집계 승인: COUNT")
            approved = understanding.model_copy(
                update={
                    "status": QueryUnderstandingStatus.SUPPORTED,
                    "execution_trace": tuple(trace),
                }
            )
            return query.model_copy(
                update={
                    "route_hint": RouteHint.STRUCTURED,
                    "structured_query": plan,
                    "understanding": approved,
                }
            )

        semantic_keys = understanding.semantic_keys
        if not semantic_keys:
            return _unsupported(
                query,
                "unknown_semantic_key",
                [*trace, "semantic key 승인: 실패"],
            )
        if len(semantic_keys) != 1:
            return _unsupported(
                query,
                "semantic_field_distinction_unapproved",
                [*trace, "semantic field 구분: 미승인"],
            )

        semantic_key = semantic_keys[0]
        trace.append(
            f"필드 grounding: {understanding.requested_field_alias} → {semantic_key}"
        )
        g3_approval = get_semantic_field_approval(table, semantic_key)
        g2_mapping = get_confirmed_field_map(table).get(semantic_key)
        if g3_approval is None and g2_mapping is None:
            return _unsupported(
                query,
                "unknown_semantic_key",
                [*trace, "semantic key 승인: 실패"],
            )
        if (
            g3_approval is not None
            and g3_approval.concept.status is not ClaimStatus.CONFIRMED
        ):
            return _unsupported(
                query,
                "semantic_concept_not_confirmed",
                [*trace, "concept 승인: 실패"],
            )

        filters: list[StructuredFilter] = []
        for condition in understanding.filter_conditions:
            operation = condition.operator.value
            if condition.unit_token is not None:
                if g3_approval is not None or (
                    g2_mapping is not None
                    and g2_mapping.unit_status is not CoreUnitStatus.CONFIRMED
                ):
                    return _unsupported(
                        query,
                        "unit_conversion_not_approved",
                        [*trace, f"단위 변환 승인: 실패 ({condition.unit_token})"],
                    )
            if g3_approval is not None:
                allowed = operation in g3_approval.open_operations
            else:
                assert g2_mapping is not None
                allowed = operation in g2_mapping.allowed_operations
            if not allowed:
                return _unsupported(
                    query,
                    "semantic_operation_not_open",
                    [*trace, f"연산 승인: {operation} CLOSED"],
                )
            filters.append(
                StructuredFilter(
                    field=semantic_key,
                    operator=condition.operator,
                    value=condition.value,
                )
            )
            trace.append(f"연산 승인: {operation}")

        sort: StructuredSort | None = None
        if understanding.sort_direction is not None:
            direction = understanding.sort_direction
            if g3_approval is not None:
                sort_operation = f"SORT_{direction.value}"
                allowed = sort_operation in g3_approval.open_operations
            else:
                sort_operation = "SORT"
                assert g2_mapping is not None
                allowed = sort_operation in g2_mapping.allowed_operations
            if not allowed:
                return _unsupported(
                    query,
                    "semantic_operation_not_open",
                    [*trace, f"연산 승인: SORT_{direction.value} CLOSED"],
                )
            sort = StructuredSort(field=semantic_key, direction=direction)
            trace.append(f"연산 승인: SORT_{direction.value}")

        if not filters and sort is None:
            return _unsupported(
                query,
                "query_operation_not_recognized",
                [*trace, "연산 승인: 대상 없음"],
            )

        if understanding.limit is not None:
            trace.append(f"Top-N 승인: {understanding.limit}")
        projections = (
            get_default_projection_keys(table, semantic_key)
            if g3_approval is not None
            else (semantic_key,)
        )
        plan = StructuredQueryContract(
            product_scope=table,
            filters=tuple(filters),
            projections=projections,
            sort=sort,
            limit=understanding.limit,
        )
        approved_understanding = understanding.model_copy(
            update={
                "status": QueryUnderstandingStatus.SUPPORTED,
                "execution_trace": tuple(trace),
            }
        )
        return query.model_copy(
            update={
                "filters": {item.field: item.value for item in filters},
                "projections": projections,
                "sort": (
                    (f"{semantic_key}:{sort.direction.value}",)
                    if sort is not None
                    else ()
                ),
                "limit": understanding.limit,
                "ambiguity": (),
                "route_hint": RouteHint.STRUCTURED,
                "structured_query": plan,
                "understanding": approved_understanding,
            }
        )
