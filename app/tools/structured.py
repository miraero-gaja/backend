"""Structured retrieval boundary; SQL and finance schemas are not implemented."""

from app.tools import UnavailableToolAdapter


class StructuredToolAdapter(UnavailableToolAdapter):
    tool_name = "structured"

