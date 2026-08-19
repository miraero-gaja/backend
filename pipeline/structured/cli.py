"""Command-line entry point for the G2-B structured baseline."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

from .runner import run_g2b, run_g2b_live_validation


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
    parser.add_argument(
        "--live-validate-db",
        action="store_true",
        help=(
            "Run read-only Live Structured Query Validation against the "
            "already-loaded PostgreSQL staging tables and record the result "
            "into the existing G2-B report set at --output-dir. Never loads, "
            "replaces, or reloads any data. Requires an existing report whose "
            "database.status is PASS. DATABASE_URL is read from the "
            "environment only and is never printed or reported. Mutually "
            "exclusive with --execute-db."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.execute_db and args.live_validate_db:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "--execute-db and --live-validate-db are mutually exclusive.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    if args.live_validate_db:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "reason": "DATABASE_URL is not configured; live validation cannot run.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        result = run_g2b_live_validation(
            raw_dir=args.raw_dir,
            schema_dir=args.schema_dir,
            g1_report_dir=args.g1_report_dir,
            g2a_report_dir=args.g2a_report_dir,
            g2b_report_dir=args.output_dir,
            database_url=database_url,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == "PASS":
            return 0
        if result["status"] == "PARTIAL":
            return 2
        return 1

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
