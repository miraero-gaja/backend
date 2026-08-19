"""Conservative parser that creates no financial concepts without a schema."""

from app.agent.contracts import QueryContract, RouteHint


class QueryParser:
    """Build the minimum safe contract until semantic parsing is implemented."""

    def parse(self, *, request_id: str, question_id: str, question: str) -> QueryContract:
        missing_inputs = tuple(
            name
            for name, value in (("question_id", question_id), ("question", question))
            if not value.strip()
        )
        return QueryContract(
            request_id=request_id,
            question_id=question_id,
            ambiguity=("semantic_parser_not_connected",),
            required_inputs=missing_inputs,
            route_hint=RouteHint.UNSUPPORTED,
        )

