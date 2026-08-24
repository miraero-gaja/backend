from pathlib import Path

from pipeline.profiling.statistics import ColumnAccumulator, DistinctDigestStore


def _profile(values: list[object], tmp_path: Path) -> dict[str, object]:
    with DistinctDigestStore(tmp_path / "distinct.sqlite3") as store:
        accumulator = ColumnAccumulator(slot=0, distinct_store=store)
        for value in values:
            accumulator.update(value)
        distinct_count = store.counts().get(0, 0)
        return accumulator.finalise(
            row_count=len(values),
            distinct_count=distinct_count,
        )


def test_numeric_like_profile_records_parseability_extrema_and_null_policy(
    tmp_path: Path,
) -> None:
    profile = _profile(["1.20", "3.40", "1.20", None], tmp_path)

    assert profile["null_count"] == 1
    numeric = profile["numeric_like_string"]
    assert numeric == {
        "candidate": True,
        "match_count": 3,
        "string_value_count": 3,
        "invalid_count": 0,
        "decimal_scales": [2],
        "numeric_min": "1.20",
        "numeric_max": "3.40",
        "exact_decimal_ordering_candidate": True,
        "nulls_require_explicit_ordering": True,
        "interpretation": (
            "source-native finite Decimal parsing only; no unit or financial "
            "meaning is inferred"
        ),
    }


def test_low_cardinality_code_counts_preserve_distribution_not_meaning(
    tmp_path: Path,
) -> None:
    profile = _profile(["101"] * 60 + ["102"] * 40, tmp_path)

    assert profile["enum_code_candidate"] is True
    assert profile["bounded_code_value_counts"] == {
        "included": True,
        "complete": True,
        "max_distinct_values": 100,
        "values": [
            {"value": "101", "count": 60},
            {"value": "102", "count": 40},
        ],
        "interpretation": (
            "observed source tokens and counts only; code meanings are not inferred"
        ),
    }
