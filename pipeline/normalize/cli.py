"""Command-line entry point for the offline G2-A contract build."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .constants import EXPECTED_COVERAGE_COLUMN_COUNT
from .runner import run_g2a


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic typed-staging and "
            f"{EXPECTED_COVERAGE_COLUMN_COUNT}-column coverage reports "
            "without modifying source workbooks."
        )
    )
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--schema-dir", required=True)
    parser.add_argument("--g1-report-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_g2a(
        raw_dir=args.raw_dir,
        schema_dir=args.schema_dir,
        g1_report_dir=args.g1_report_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


__all__ = ["build_parser", "main"]
