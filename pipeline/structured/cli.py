"""Command-line entry point for the G2-B structured baseline."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

from .runner import run_g2b


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the official typed staging and structured-query contracts, "
            "with optional explicit PostgreSQL loading."
        )
    )
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--schema-dir", required=True)
    parser.add_argument("--g1-report-dir", required=True)
    parser.add_argument("--g2a-report-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument(
        "--execute-db",
        action="store_true",
        help=(
            "Explicitly allow PostgreSQL staging load. DATABASE_URL is read "
            "from the environment only and is never printed or reported."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL") if args.execute_db else None
    result = run_g2b(
        raw_dir=args.raw_dir,
        schema_dir=args.schema_dir,
        g1_report_dir=args.g1_report_dir,
        g2a_report_dir=args.g2a_report_dir,
        output_dir=args.output_dir,
        execute_database=args.execute_db,
        database_url=database_url,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "PASS":
        return 0
    if result["status"] == "PARTIAL":
        return 2
    return 1


__all__ = ["build_parser", "main"]
