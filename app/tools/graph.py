"""Graph retrieval boundary; no graph engine is selected by the skeleton."""

from app.tools import UnavailableToolAdapter


class GraphToolAdapter(UnavailableToolAdapter):
    tool_name = "graph"

