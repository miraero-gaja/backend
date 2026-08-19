"""Cost-rule boundary; no fee, tax, or total-cost formula is assumed here."""

from app.tools import UnavailableToolAdapter


class CostRulesToolAdapter(UnavailableToolAdapter):
    tool_name = "cost_rules"

