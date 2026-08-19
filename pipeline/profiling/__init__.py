"""Read-only G1 workbook profiling.

The online application does not import this optional data pipeline. Importing
``pipeline.profiling`` therefore does not require the Excel dependency until a
profiling run is actually started.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_profiling(
    raw_dir: str | Path,
    schema_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run G1 profiling; imported lazily to keep API runtime dependencies separate."""

    from .runner import run_profiling as _run_profiling

    return _run_profiling(raw_dir, schema_dir, output_dir)


__all__ = ["run_profiling"]

