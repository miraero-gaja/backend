"""Whitespace review detects collisions without mutating or exposing values."""

from __future__ import annotations

from pipeline.normalize import TrimStatus, analyze_trim_impact


def test_trim_collision_downgrades_identifier_uniqueness() -> None:
    source_values = ["A", " A", "B"]
    original_snapshot = tuple(source_values)

    analysis = analyze_trim_impact(source_values, identifier=True)

    assert tuple(source_values) == original_snapshot
    assert analysis.distinct_count_before_trim == 3
    assert analysis.distinct_count_after_trim == 2
    assert analysis.collapsed_distinct_count == 1
    assert analysis.collision_group_count == 1
    assert analysis.trim_collision_detected is True
    assert analysis.trim_status is TrimStatus.CONFLICT
    assert analysis.identifier_unique_before_trim is True
    assert analysis.identifier_unique_after_trim is False
    assert analysis.identifier_uniqueness_changed is True


def test_whitespace_analysis_report_contains_aggregates_only() -> None:
    analysis = analyze_trim_impact([" secret", "secret", "   ", None])
    payload = analysis.to_dict()

    assert payload["trim_status"] == "CONFLICT"
    assert payload["whitespace_only_count"] == 1
    assert not any("raw" in key or "digest" in key or "value_sample" in key for key in payload)
    assert " secret" not in repr(payload)


def test_blank_identifier_is_not_reported_as_unique() -> None:
    analysis = analyze_trim_impact(["A", ""], identifier=True)

    assert analysis.empty_string_count == 1
    assert analysis.null_class_count == 1
    assert analysis.identifier_unique_before_trim is False
    assert analysis.identifier_unique_after_trim is False
    assert analysis.identifier_uniqueness_changed is False
