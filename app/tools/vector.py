"""Vector retrieval boundary; embeddings and indexes are intentionally absent."""

from app.tools import UnavailableToolAdapter


class VectorToolAdapter(UnavailableToolAdapter):
    tool_name = "vector"

