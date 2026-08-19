"""Ontology-grounding boundary; intentionally inert before schema profiling."""

from app.agent.contracts import QueryContract, RouteHint


class OntologyGrounder:
    """Prevent an ungrounded contract from being routed to retrieval tools."""

    def ground(self, query: QueryContract) -> QueryContract:
        if (
            query.structured_query is not None
            and not query.required_inputs
            and not query.ambiguity
        ):
            return query.model_copy(update={"route_hint": RouteHint.STRUCTURED})
        return query.model_copy(update={"route_hint": RouteHint.UNSUPPORTED})
