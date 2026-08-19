"""Streaming, value-safe column statistics for G1 profiling."""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import struct
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


_NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?$")
_CODE_TEXT = re.compile(r"^[A-Za-z0-9_.:/+-]+$")
_PERCENT_TEXT = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?%$"
)
_BOOLEAN_CODE_SETS = (
    frozenset({"Y", "N"}),
    frozenset({"YES", "NO"}),
    frozenset({"TRUE", "FALSE"}),
    frozenset({"T", "F"}),
    frozenset({"0", "1"}),
)
_TYPE_ORDER = {
    "boolean": 0,
    "integer": 1,
    "number": 2,
    "decimal": 3,
    "date": 4,
    "datetime": 5,
    "time": 6,
    "string": 7,
    "formula": 8,
    "excel_error": 9,
    "other": 10,
}


def is_blank_value(value: Any) -> bool:
    """Treat missing, empty, and whitespace-only strings as observed blanks."""

    return value is None or (isinstance(value, str) and value.strip() == "")


def value_type(value: Any, *, excel_data_type: str | None = None) -> str:
    """Return a stable observed Excel/Python type label."""

    if excel_data_type == "e":
        return "excel_error"
    if excel_data_type == "f":
        return "formula"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "other"


def _canonical_bytes(value: Any, *, type_label: str | None = None) -> bytes:
    label = type_label or value_type(value)
    if isinstance(value, float):
        encoded_value = value.hex().encode("ascii")
    elif isinstance(value, (datetime, date, time)):
        encoded_value = value.isoformat().encode("utf-8")
    elif isinstance(value, bytes):
        encoded_value = value
    else:
        encoded_value = str(value).encode("utf-8", errors="surrogatepass")
    return label.encode("ascii") + b":" + encoded_value


def typed_value_digest(value: Any, *, type_label: str | None = None) -> bytes:
    """Return a typed SHA-256 digest so raw values never enter the temp store."""

    return hashlib.sha256(_canonical_bytes(value, type_label=type_label)).digest()


def composite_digest(values: list[tuple[Any, str]]) -> bytes:
    """Hash an ordered typed tuple without ambiguous concatenation."""

    digest = hashlib.sha256()
    for value, type_label in values:
        encoded = _canonical_bytes(value, type_label=type_label)
        digest.update(struct.pack(">I", len(encoded)))
        digest.update(encoded)
    return digest.digest()


class DistinctDigestStore:
    """Disk-backed exact-on-SHA-256-digests distinct counter.

    Only cryptographic typed digests are retained, never source values or rows.
    The caller owns the temporary directory containing ``database_path``.
    """

    def __init__(self, database_path: Path, *, batch_size: int = 20_000) -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.execute("PRAGMA journal_mode=OFF")
        self._connection.execute("PRAGMA synchronous=OFF")
        self._connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        self._connection.execute(
            "CREATE TABLE distinct_digest ("
            "slot INTEGER NOT NULL, digest BLOB NOT NULL, "
            "PRIMARY KEY (slot, digest)) WITHOUT ROWID"
        )
        self._batch_size = batch_size
        # Deduplicate within each batch before crossing the Python/SQLite
        # boundary. Low-cardinality code columns then generate very few writes.
        self._pending: set[tuple[int, bytes]] = set()

    def add_digest(self, slot: int, digest: bytes) -> None:
        self._pending.add((slot, digest))
        if len(self._pending) >= self._batch_size:
            self.flush()

    def add_value(self, slot: int, value: Any, *, type_label: str) -> None:
        self.add_digest(slot, typed_value_digest(value, type_label=type_label))

    def flush(self) -> None:
        if not self._pending:
            return
        with self._connection:
            self._connection.executemany(
                "INSERT OR IGNORE INTO distinct_digest(slot, digest) VALUES (?, ?)",
                self._pending,
            )
        self._pending.clear()

    def counts(self) -> dict[int, int]:
        self.flush()
        return {
            int(slot): int(count)
            for slot, count in self._connection.execute(
                "SELECT slot, COUNT(*) FROM distinct_digest GROUP BY slot"
            )
        }

    def close(self) -> None:
        self.flush()
        self._connection.close()

    def __enter__(self) -> "DistinctDigestStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _decimal_scale(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return max(0, -int(exponent))


def _parse_numeric_text(value: str) -> Decimal | None:
    if not value or value[0] not in "+-.0123456789":
        return None
    if _NUMERIC_TEXT.fullmatch(value) is None:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _date_format(value: str) -> str | None:
    # Shape checks avoid raising several ``strptime`` exceptions for every
    # ordinary name/description string in the large source workbooks.
    if len(value) == 8 and value.isascii() and value.isdigit():
        try:
            date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
        except ValueError:
            return None
        return "YYYYMMDD"
    if (
        len(value) == 10
        and value[4] == value[7]
        and value[4] in "-/"
        and (value[0:4] + value[5:7] + value[8:10]).isascii()
        and (value[0:4] + value[5:7] + value[8:10]).isdigit()
    ):
        try:
            date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
        except ValueError:
            return None
        return "YYYY-MM-DD" if value[4] == "-" else "YYYY/MM/DD"
    if (
        len(value) == 19
        and value[4] == "-"
        and value[7] == "-"
        and value[10] == " "
        and value[13] == ":"
        and value[16] == ":"
    ):
        digits = value[0:4] + value[5:7] + value[8:10] + value[11:13] + value[14:16] + value[17:19]
        if digits.isascii() and digits.isdigit():
            try:
                datetime(
                    int(value[0:4]),
                    int(value[5:7]),
                    int(value[8:10]),
                    int(value[11:13]),
                    int(value[14:16]),
                    int(value[17:19]),
                )
            except ValueError:
                return None
            return "YYYY-MM-DD HH:MM:SS"
    return None


def _safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 8) if denominator else 0.0


class ColumnAccumulator:
    """Mutable streaming accumulator that emits a JSON-safe profile."""

    def __init__(self, *, slot: int, distinct_store: DistinctDigestStore) -> None:
        self.slot = slot
        self._distinct_store = distinct_store
        self.missing_cell_count = 0
        self.empty_string_count = 0
        self.whitespace_only_count = 0
        self.leading_or_trailing_whitespace_count = 0
        self.excel_error_count = 0
        self.formula_count = 0
        self.type_counts: Counter[str] = Counter()
        self.numeric_count = 0
        self.numeric_min: Decimal | None = None
        self.numeric_max: Decimal | None = None
        self.non_finite_numeric_count = 0
        self.actual_numeric_scales: set[int] = set()
        self.date_count = 0
        self.date_min: str | None = None
        self.date_max: str | None = None
        self.string_count = 0
        self.string_length_min: int | None = None
        self.string_length_max: int | None = None
        self.numeric_like_string_count = 0
        self.numeric_like_scales: set[int] = set()
        self.date_like_string_count = 0
        self.integer_value_count = 0
        self.date_like_integer_count = 0
        self.date_format_counts: Counter[str] = Counter()
        self.code_like_string_count = 0
        self.percent_literal_count = 0
        self._bounded_tokens: set[str] = set()
        self._bounded_tokens_overflow = False

    def _observe_numeric(self, value: Any) -> None:
        if isinstance(value, Decimal):
            number = value
        elif isinstance(value, int):
            number = Decimal(value)
        elif isinstance(value, float) and math.isfinite(value):
            number = Decimal(str(value))
        else:
            self.non_finite_numeric_count += 1
            return
        if not number.is_finite():
            self.non_finite_numeric_count += 1
            return
        self.numeric_count += 1
        self.numeric_min = number if self.numeric_min is None else min(self.numeric_min, number)
        self.numeric_max = number if self.numeric_max is None else max(self.numeric_max, number)
        self.actual_numeric_scales.add(_decimal_scale(number))
        if isinstance(value, int) and not isinstance(value, bool):
            self.integer_value_count += 1
            encoded = str(value)
            if len(encoded) == 8 and _date_format(encoded) == "YYYYMMDD":
                self.date_like_integer_count += 1

    def _observe_date(self, value: date | datetime) -> None:
        encoded = value.isoformat()
        self.date_count += 1
        self.date_min = encoded if self.date_min is None else min(self.date_min, encoded)
        self.date_max = encoded if self.date_max is None else max(self.date_max, encoded)

    def _observe_string(self, value: str) -> None:
        self.string_count += 1
        if value != value.strip():
            self.leading_or_trailing_whitespace_count += 1

        stripped = value.strip()
        if stripped == "":
            return
        # Length extrema describe nonblank strings. Empty and whitespace-only
        # strings remain visible through their dedicated counters above.
        length = len(value)
        self.string_length_min = (
            length if self.string_length_min is None else min(self.string_length_min, length)
        )
        self.string_length_max = (
            length if self.string_length_max is None else max(self.string_length_max, length)
        )
        numeric = _parse_numeric_text(stripped)
        if numeric is not None:
            self.numeric_like_string_count += 1
            self.numeric_like_scales.add(_decimal_scale(numeric))
        date_format = _date_format(stripped)
        if date_format is not None:
            self.date_like_string_count += 1
            self.date_format_counts[date_format] += 1
        if len(stripped) <= 64 and _CODE_TEXT.fullmatch(stripped) is not None:
            self.code_like_string_count += 1
        if stripped.endswith("%") and _PERCENT_TEXT.fullmatch(stripped) is not None:
            self.percent_literal_count += 1

        if not self._bounded_tokens_overflow:
            if len(stripped) > 5:
                self._bounded_tokens.clear()
                self._bounded_tokens_overflow = True
            else:
                self._bounded_tokens.add(stripped.upper())
                if len(self._bounded_tokens) > 4:
                    self._bounded_tokens.clear()
                    self._bounded_tokens_overflow = True

    def update(self, value: Any, *, excel_data_type: str | None = None) -> None:
        if value is None:
            # openpyxl exposes a physically present empty inline-string cell as
            # ``None`` with ``data_type='inlineStr'``. Keep it separate from an
            # absent cell while counting both as null/blank for completeness.
            if excel_data_type == "inlineStr":
                self.empty_string_count += 1
                self._observe_string("")
            else:
                self.missing_cell_count += 1
            return
        if isinstance(value, str):
            if value == "":
                self.empty_string_count += 1
                self._observe_string(value)
                return
            if value.strip() == "":
                self.whitespace_only_count += 1
                self._observe_string(value)
                return

        observed_type = value_type(value, excel_data_type=excel_data_type)
        self.type_counts[observed_type] += 1
        if observed_type == "excel_error":
            self.excel_error_count += 1
        elif observed_type == "formula":
            self.formula_count += 1
        elif observed_type in {"integer", "number", "decimal"}:
            self._observe_numeric(value)
        elif observed_type in {"date", "datetime"}:
            self._observe_date(value)
        elif observed_type == "string":
            self._observe_string(value)

        self._distinct_store.add_value(self.slot, value, type_label=observed_type)

    def finalise(self, *, row_count: int, distinct_count: int) -> dict[str, Any]:
        null_count = (
            self.missing_cell_count + self.empty_string_count + self.whitespace_only_count
        )
        non_null_count = row_count - null_count
        duplicate_count = max(0, non_null_count - distinct_count)
        duplicate_ratio = _safe_ratio(duplicate_count, non_null_count)
        if duplicate_count == 0:
            duplicate_tendency = "NONE"
        elif duplicate_ratio <= 0.01:
            duplicate_tendency = "LOW"
        elif duplicate_ratio <= 0.20:
            duplicate_tendency = "MODERATE"
        else:
            duplicate_tendency = "HIGH"

        ordered_types = sorted(self.type_counts, key=lambda label: _TYPE_ORDER.get(label, 99))
        representative_type = None
        if self.type_counts:
            representative_type = min(
                self.type_counts,
                key=lambda label: (-self.type_counts[label], _TYPE_ORDER.get(label, 99)),
            )
        only_actual_numeric = bool(ordered_types) and set(ordered_types) <= {
            "integer",
            "number",
            "decimal",
        }
        only_actual_date = bool(ordered_types) and set(ordered_types) <= {"date", "datetime"}
        string_nonblank_count = self.type_counts.get("string", 0)
        boolean_tokens = (
            sorted(self._bounded_tokens)
            if not self._bounded_tokens_overflow
            and len(self._bounded_tokens) == 2
            and frozenset(self._bounded_tokens) in _BOOLEAN_CODE_SETS
            else []
        )
        enum_candidate = (
            non_null_count > 0
            and distinct_count <= 100
            and _safe_ratio(distinct_count, non_null_count) <= 0.05
        )

        return {
            "row_count": row_count,
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_ratio": _safe_ratio(null_count, row_count),
            "missing_cell_count": self.missing_cell_count,
            "empty_string_count": self.empty_string_count,
            "whitespace_only_count": self.whitespace_only_count,
            "observed_nullable": null_count > 0,
            "distinct_count": distinct_count,
            "distinct_count_method": "typed_sha256_digest",
            "duplicate_count": duplicate_count,
            "duplicate_ratio": duplicate_ratio,
            "duplicate_tendency": duplicate_tendency,
            "observed_types": ordered_types,
            "observed_type_counts": {
                label: self.type_counts[label] for label in ordered_types
            },
            "representative_value_type": representative_type,
            "mixed_value_types": len(ordered_types) > 1,
            "numeric_min": str(self.numeric_min) if only_actual_numeric else None,
            "numeric_max": str(self.numeric_max) if only_actual_numeric else None,
            "non_finite_numeric_count": self.non_finite_numeric_count,
            "date_min": self.date_min if only_actual_date else None,
            "date_max": self.date_max if only_actual_date else None,
            "string_length_min": self.string_length_min,
            "string_length_max": self.string_length_max,
            "leading_or_trailing_whitespace_count": (
                self.leading_or_trailing_whitespace_count
            ),
            "excel_error_count": self.excel_error_count,
            "formula_cell_count": self.formula_count,
            "numeric_like_string": {
                "candidate": string_nonblank_count > 0
                and self.numeric_like_string_count == string_nonblank_count,
                "match_count": self.numeric_like_string_count,
                "string_value_count": string_nonblank_count,
                "decimal_scales": sorted(self.numeric_like_scales),
            },
            "date_like_string": {
                "candidate": string_nonblank_count > 0
                and self.date_like_string_count == string_nonblank_count,
                "match_count": self.date_like_string_count,
                "string_value_count": string_nonblank_count,
                "formats": dict(sorted(self.date_format_counts.items())),
            },
            "date_like_integer": {
                "candidate": self.integer_value_count > 0
                and self.date_like_integer_count == self.integer_value_count
                and set(ordered_types) == {"integer"},
                "match_count": self.date_like_integer_count,
                "integer_value_count": self.integer_value_count,
                "format": "YYYYMMDD" if self.date_like_integer_count else None,
                "interpretation": "lexical/value-shape candidate only",
            },
            "code_like_string": {
                "candidate": string_nonblank_count > 0
                and self.code_like_string_count == string_nonblank_count,
                "match_count": self.code_like_string_count,
                "string_value_count": string_nonblank_count,
            },
            "enum_code_candidate": enum_candidate,
            "boolean_code_candidate": bool(boolean_tokens),
            "boolean_code_representation": boolean_tokens,
            "percent_literal_count": self.percent_literal_count,
            "actual_numeric_decimal_scales": sorted(self.actual_numeric_scales),
        }
