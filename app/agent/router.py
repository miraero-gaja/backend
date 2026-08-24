"""Deterministic route selection over a validated query contract."""

from app.agent.contracts import (
    QueryContract,
    QueryUnderstandingStatus,
    RouteHint,
)


class QueryRouter:
    def route(self, query: QueryContract) -> RouteHint:
        if query.required_inputs:
            return RouteHint.UNSUPPORTED
        if query.understanding is not None and query.understanding.status in {
            QueryUnderstandingStatus.AMBIGUOUS,
            QueryUnderstandingStatus.UNSUPPORTED,
        }:
            return RouteHint.UNSUPPORTED
        if query.route_hint is RouteHint.STRUCTURED and query.structured_query is None:
            return RouteHint.UNSUPPORTED
        return query.route_hint
