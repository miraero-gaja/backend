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


def is_cross_product_metric_compatible(metric: AggregateFunction) -> bool:
    """Return True only for metrics approved for cross-scope merging."""

    return metric in _CROSS_PRODUCT_COMPATIBLE_METRICS
