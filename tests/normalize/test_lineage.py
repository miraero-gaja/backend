"""Source-row lineage must be deterministic and ambiguity-resistant."""

from __future__ import annotations

import re

import pytest

from pipeline.normalize import build_source_lineage, derive_source_row_id


SYNTHETIC_FILE_HASH = "ab" * 32


def _derive(*, table: str, sheet: str, row: int = 2) -> str:
    return derive_source_row_id(
        source_table=table,
        source_file_sha256=SYNTHETIC_FILE_HASH,
        source_sheet=sheet,
        source_excel_row=row,
    )


def test_source_row_id_is_deterministic_and_has_versioned_digest_shape() -> None:
    first = _derive(table="SYNTHETIC", sheet="datarows")
    second = _derive(table="SYNTHETIC", sheet="datarows")

    assert first == second
    assert re.fullmatch(r"srid:v1:[0-9a-f]{64}", first)


def test_length_prefixed_lineage_encoding_is_collision_safe() -> None:
    # These pairs would be ambiguous under a naive ``table|sheet`` join.
    left = _derive(table="alpha|beta", sheet="gamma")
    right = _derive(table="alpha", sheet="beta|gamma")

    assert left != right
    assert _derive(table="SYNTHETIC", sheet="datarows", row=2) != _derive(
        table="SYNTHETIC", sheet="datarows", row=3
    )


def test_source_lineage_is_not_derived_from_a_business_key() -> None:
    lineage = build_source_lineage(
        source_table="PREF01N001",
        source_file_sha256=SYNTHETIC_FILE_HASH.upper(),
        source_sheet="datarows",
        source_excel_row=2,
    )

    assert lineage.source_file_sha256 == SYNTHETIC_FILE_HASH
    assert set(lineage.to_dict()) == {
        "source_table",
        "source_file_sha256",
        "source_sheet",
        "source_excel_row",
        "source_row_id",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_file_sha256": "not-a-sha256"},
        {"source_excel_row": 0},
        {"source_excel_row": True},
        {"source_table": ""},
        {"source_sheet": ""},
    ],
)
def test_invalid_lineage_components_are_rejected(overrides: dict[str, object]) -> None:
    kwargs: dict[str, object] = {
        "source_table": "SYNTHETIC",
        "source_file_sha256": SYNTHETIC_FILE_HASH,
        "source_sheet": "datarows",
        "source_excel_row": 2,
    }
    kwargs.update(overrides)

    with pytest.raises(ValueError):
        derive_source_row_id(**kwargs)  # type: ignore[arg-type]

