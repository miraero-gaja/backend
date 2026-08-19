"""Deterministic, business-key-independent source-row lineage."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


SOURCE_ROW_ID_VERSION = "v1"
_DOMAIN = b"miraeasset-financial-agent/source-row-id\x00v1\x00"
_SHA256 = re.compile(r"[0-9a-fA-F]{64}", re.ASCII)


def _length_prefix(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(8, byteorder="big", signed=False) + encoded


def _validate_components(
    source_table: str,
    source_file_sha256: str,
    source_sheet: str,
    source_excel_row: int,
) -> tuple[str, str, str, int]:
    if not isinstance(source_table, str) or source_table == "":
        raise ValueError("source_table must be a non-empty string")
    if not isinstance(source_sheet, str) or source_sheet == "":
        raise ValueError("source_sheet must be a non-empty string")
    if not isinstance(source_file_sha256, str) or not _SHA256.fullmatch(
        source_file_sha256
    ):
        raise ValueError("source_file_sha256 must be exactly 64 hexadecimal digits")
    if (
        isinstance(source_excel_row, bool)
        or not isinstance(source_excel_row, int)
        or source_excel_row < 1
    ):
        raise ValueError("source_excel_row must be a positive integer")
    return (
        source_table,
        source_file_sha256.casefold(),
        source_sheet,
        source_excel_row,
    )


def derive_source_row_id(
    *,
    source_table: str,
    source_file_sha256: str,
    source_sheet: str,
    source_excel_row: int,
) -> str:
    """Derive a stable source row ID from an unambiguous versioned encoding.

    The SHA-256 input is a domain/version prefix followed by four UTF-8 fields,
    each encoded with an unsigned 8-byte length prefix.  The row number uses its
    canonical base-10 representation.  Delimiter characters inside table or
    sheet names therefore cannot produce ambiguous identities.
    """

    table, file_hash, sheet, excel_row = _validate_components(
        source_table,
        source_file_sha256,
        source_sheet,
        source_excel_row,
    )
    payload = b"".join(
        (
            _DOMAIN,
            _length_prefix(table),
            _length_prefix(file_hash),
            _length_prefix(sheet),
            _length_prefix(str(excel_row)),
        )
    )
    digest = hashlib.sha256(payload).hexdigest()
    return f"srid:{SOURCE_ROW_ID_VERSION}:{digest}"


@dataclass(frozen=True, slots=True)
class SourceLineage:
    """Required technical lineage for one physical datarows row."""

    source_table: str
    source_file_sha256: str
    source_sheet: str
    source_excel_row: int
    source_row_id: str

    @classmethod
    def create(
        cls,
        *,
        source_table: str,
        source_file_sha256: str,
        source_sheet: str,
        source_excel_row: int,
    ) -> "SourceLineage":
        table, file_hash, sheet, excel_row = _validate_components(
            source_table,
            source_file_sha256,
            source_sheet,
            source_excel_row,
        )
        return cls(
            source_table=table,
            source_file_sha256=file_hash,
            source_sheet=sheet,
            source_excel_row=excel_row,
            source_row_id=derive_source_row_id(
                source_table=table,
                source_file_sha256=file_hash,
                source_sheet=sheet,
                source_excel_row=excel_row,
            ),
        )

    def __post_init__(self) -> None:
        table, file_hash, sheet, excel_row = _validate_components(
            self.source_table,
            self.source_file_sha256,
            self.source_sheet,
            self.source_excel_row,
        )
        expected = derive_source_row_id(
            source_table=table,
            source_file_sha256=file_hash,
            source_sheet=sheet,
            source_excel_row=excel_row,
        )
        if self.source_file_sha256 != file_hash:
            raise ValueError("source_file_sha256 must use canonical lowercase hex")
        if self.source_row_id != expected:
            raise ValueError("source_row_id does not match its lineage components")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_table": self.source_table,
            "source_file_sha256": self.source_file_sha256,
            "source_sheet": self.source_sheet,
            "source_excel_row": self.source_excel_row,
            "source_row_id": self.source_row_id,
        }


def build_source_lineage(
    *,
    source_table: str,
    source_file_sha256: str,
    source_sheet: str,
    source_excel_row: int,
) -> SourceLineage:
    """Functional alias for callers that do not need the class constructor."""

    return SourceLineage.create(
        source_table=source_table,
        source_file_sha256=source_file_sha256,
        source_sheet=source_sheet,
        source_excel_row=source_excel_row,
    )


__all__ = [
    "SOURCE_ROW_ID_VERSION",
    "SourceLineage",
    "build_source_lineage",
    "derive_source_row_id",
]
