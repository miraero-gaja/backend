"""Contract tests for read-only G1 workbook discovery."""

from __future__ import annotations

import hashlib
import os

import pytest

from pipeline.profiling.discovery import (
    DiscoveryError,
    discover_workbooks,
    map_logical_table_id,
    sha256_file,
    verify_sources_unchanged,
)


EXPECTED_TABLE_IDS = (
    "PRBD01N001",
    "PREF01N001",
    "PREF02N001",
    "PRFD01N001",
)


def test_physical_fund_alias_maps_to_canonical_logical_id() -> None:
    assert (
        map_logical_table_id("PRFDN001_synthetic_20260711_datarows.xlsx")
        == "PRFD01N001"
    )
    assert (
        map_logical_table_id("PRFD01N001_synthetic_schema.xlsx")
        == "PRFD01N001"
    )
    assert map_logical_table_id("UNKNOWN_synthetic.xlsx") is None


def test_discovery_returns_one_raw_and_schema_source_per_table(
    synthetic_workbooks,
) -> None:
    sources = discover_workbooks(
        synthetic_workbooks.raw_dir,
        synthetic_workbooks.schema_dir,
    )

    assert len(sources) == 8
    assert tuple(source.logical_table_id for source in sources[:4]) == EXPECTED_TABLE_IDS
    assert tuple(source.logical_table_id for source in sources[4:]) == EXPECTED_TABLE_IDS
    assert {source.source_kind for source in sources[:4]} == {"datarows"}
    assert {source.source_kind for source in sources[4:]} == {"schema"}
    assert all(source.path.is_absolute() for source in sources)
    assert all(source.extension == ".xlsx" for source in sources)

    alias_source = next(
        source
        for source in sources
        if source.source_kind == "datarows"
        and source.logical_table_id == "PRFD01N001"
    )
    assert alias_source.physical_filename.startswith("PRFDN001_")
    assert alias_source.path.name == alias_source.physical_filename


def test_sha256_is_deterministic_and_matches_standard_library(
    synthetic_workbooks,
) -> None:
    source_path = synthetic_workbooks.raw_paths["PRBD01N001"]
    expected = hashlib.sha256(source_path.read_bytes()).hexdigest()

    assert sha256_file(source_path) == expected
    assert sha256_file(source_path, chunk_size=7) == expected
    assert sha256_file(source_path, chunk_size=64 * 1024) == expected


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown"])
def test_discovery_rejects_incomplete_or_ambiguous_source_sets(
    synthetic_workbooks,
    problem: str,
) -> None:
    if problem == "missing":
        synthetic_workbooks.raw_paths["PREF02N001"].unlink()
    elif problem == "duplicate":
        duplicate = synthetic_workbooks.raw_dir / "PREF01N001_duplicate_datarows.xlsx"
        duplicate.write_bytes(
            synthetic_workbooks.raw_paths["PREF01N001"].read_bytes()
        )
    else:
        unknown = synthetic_workbooks.schema_dir / "UNKNOWN_synthetic_schema.xlsx"
        unknown.write_bytes(
            synthetic_workbooks.schema_paths["PRBD01N001"].read_bytes()
        )

    with pytest.raises(DiscoveryError):
        discover_workbooks(
            synthetic_workbooks.raw_dir,
            synthetic_workbooks.schema_dir,
        )


def test_source_verifier_detects_byte_change_even_when_metadata_is_restored(
    synthetic_workbooks,
) -> None:
    sources = discover_workbooks(
        synthetic_workbooks.raw_dir,
        synthetic_workbooks.schema_dir,
    )
    assert verify_sources_unchanged(sources)

    target = synthetic_workbooks.raw_paths["PRBD01N001"]
    original_stat = target.stat()
    changed = bytearray(target.read_bytes())
    changed[-1] ^= 1
    target.write_bytes(changed)
    os.utime(
        target,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )

    assert target.stat().st_size == original_stat.st_size
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert not verify_sources_unchanged(sources)
