"""Read-only discovery and fingerprinting of the eight official workbooks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .constants import TABLE_SPECS


SourceKind = Literal["datarows", "schema"]


class DiscoveryError(ValueError):
    """Raised when the official workbook set cannot be mapped unambiguously."""


@dataclass(frozen=True, slots=True)
class SourceWorkbook:
    """Immutable before-run fingerprint for one source workbook."""

    source_kind: SourceKind
    logical_table_id: str
    path: Path
    physical_filename: str
    extension: str
    size_bytes: int
    modified_time_ns: int
    modified_at_utc: str
    sha256: str


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return a deterministic SHA-256 without opening the source for writing."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def map_logical_table_id(filename: str) -> str | None:
    """Map a physical filename token to its official logical table ID.

    ``PRFDN001`` is an accepted physical alias only. It is never returned as a
    logical ID and no source file is renamed.
    """

    upper_name = filename.upper()
    matches: set[str] = set()
    for logical_id, spec in TABLE_SPECS.items():
        for token in (logical_id, *spec.physical_id_aliases):
            pattern = rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])"
            if re.search(pattern, upper_name):
                matches.add(logical_id)

    if len(matches) > 1:
        joined = ", ".join(sorted(matches))
        raise DiscoveryError(f"Ambiguous logical table mapping for {filename!r}: {joined}")
    return next(iter(matches), None)


def _resolve_directory(path: str | Path, *, label: str) -> Path:
    directory = Path(path).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise DiscoveryError(f"{label} is not a directory: {directory}")
    return directory


def _discover_kind(directory: Path, source_kind: SourceKind) -> list[SourceWorkbook]:
    paths = sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".xlsx"),
        key=lambda path: path.name.casefold(),
    )
    unknown: list[str] = []
    by_table: dict[str, list[Path]] = {table_id: [] for table_id in TABLE_SPECS}

    for path in paths:
        logical_id = map_logical_table_id(path.name)
        if logical_id is None:
            unknown.append(path.name)
        else:
            by_table[logical_id].append(path)

    problems: list[str] = []
    if unknown:
        problems.append(f"unmapped {source_kind} workbook(s): {', '.join(unknown)}")
    for logical_id, mapped_paths in by_table.items():
        if len(mapped_paths) != 1:
            names = ", ".join(path.name for path in mapped_paths) or "none"
            problems.append(
                f"expected exactly one {source_kind} workbook for {logical_id}; found {names}"
            )
    if problems:
        raise DiscoveryError("; ".join(problems))

    discovered: list[SourceWorkbook] = []
    for logical_id in TABLE_SPECS:
        path = by_table[logical_id][0]
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        discovered.append(
            SourceWorkbook(
                source_kind=source_kind,
                logical_table_id=logical_id,
                path=path,
                physical_filename=path.name,
                extension=path.suffix.lower(),
                size_bytes=stat.st_size,
                modified_time_ns=stat.st_mtime_ns,
                modified_at_utc=modified.isoformat().replace("+00:00", "Z"),
                sha256=sha256_file(path),
            )
        )
    return discovered


def discover_workbooks(
    raw_dir: str | Path,
    schema_dir: str | Path,
) -> tuple[SourceWorkbook, ...]:
    """Discover exactly one raw and schema workbook for every official table."""

    raw_directory = _resolve_directory(raw_dir, label="raw_dir")
    schema_directory = _resolve_directory(schema_dir, label="schema_dir")
    if raw_directory == schema_directory:
        raise DiscoveryError("raw_dir and schema_dir must be different directories")

    sources = [
        *_discover_kind(raw_directory, "datarows"),
        *_discover_kind(schema_directory, "schema"),
    ]
    return tuple(sources)


def verify_sources_unchanged(sources: tuple[SourceWorkbook, ...]) -> bool:
    """Verify size, timestamp, and SHA-256 against the before-run fingerprint."""

    for source in sources:
        stat = source.path.stat()
        if stat.st_size != source.size_bytes or stat.st_mtime_ns != source.modified_time_ns:
            return False
        if sha256_file(source.path) != source.sha256:
            return False
    return True

