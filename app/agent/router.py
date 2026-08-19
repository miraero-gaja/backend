"""Deterministic route selection over a validated query contract."""

from app.agent.contracts import QueryContract, RouteHint


class QueryRouter:
    def route(self, query: QueryContract) -> RouteHint:
        if query.required_inputs:
            return RouteHint.UNSUPPORTED
        return query.route_hint

