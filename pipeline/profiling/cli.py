"""Command-line interface for the offline G1 profiler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .runner import run_profiling


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile the eight official G1 XLSX files without modifying them."
    )
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--schema-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    result = run_profiling(
        raw_dir=arguments.raw_dir,
        schema_dir=arguments.schema_dir,
        output_dir=arguments.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1

