"""Deterministic compatibility gate for cross-product metric merging.

Cross-product retrieval must never force together results whose concept,
unit, or period are not actually comparable across product scopes. This
module is the single, explicit place that decides which metrics qualify --
adding a new metric here is a conscious, reviewable approval, never an
implicit side effect of grounding logic.

Only a metric whose meaning is table-scope-invariant (the same concept,
unit, and period regardless of which product scope produced it) may be
merged across scopes. COUNT is the only metric that currently qualifies:
"how many rows matched" carries the same unit (a plain integer count) and
the same concept in every logical table, with no per-table definition to
reconcile. Any other aggregate (SUM/AVG/MIN/MAX of a semantic field, or a
non-aggregate projection) is not compatible until its concept/unit/period
comparability has been explicitly reviewed and approved -- attempting to
merge those must fail closed (UNSUPPORTED), never silently coerce.
"""

from __future__ import annotations

from app.structured.contracts import AggregateFunction

_CROSS_PRODUCT_COMPATIBLE_METRICS = frozenset({AggregateFunction.COUNT})

# The current runtime has no constituent relation retrieval.  This key and
# scope selector are therefore only a compatibility seam: they make the
# official 1Y policy testable without opening a route, inventing a PREF02 1Y
# field, or changing the existing COUNT path.
ETF_CONSTITUENT_RETURN_1Y = "etf.constituent_return_1y"
_RELATION_METRIC_SCOPES = {
    ETF_CONSTITUENT_RETURN_1Y: frozenset({"PREF01N001"}),
}


def is_cross_product_metric_compatible(metric: AggregateFunction) -> bool:
    """Return True only for metrics approved for cross-scope merging."""

    return metric in _CROSS_PRODUCT_COMPATIBLE_METRICS


def compatible_relation_scopes(
    metric_key: str,
    requested_scopes: tuple[str, ...],
) -> tuple[str, ...]:
    """Return only officially compatible scopes for a future relation path.

    Unknown metrics fail closed.  For constituent-based ETF 1Y, PREF02 is
    deliberately absent because the official source has no approved 1Y value;
    no 1D annualization or alternate-period substitution is performed here.
    """

    approved_scopes = _RELATION_METRIC_SCOPES.get(metric_key)
    if approved_scopes is None:
        return ()
    return tuple(
        scope for scope in requested_scopes if scope in approved_scopes
    )
