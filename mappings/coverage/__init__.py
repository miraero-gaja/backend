"""Coverage matrix construction and validation."""

from .registry import (
    OFFICIAL_EXPECTED_COLUMN_COUNT,
    CoverageRegistryError,
    build_coverage_registry,
    validate_coverage_registry,
)

__all__ = [
    "OFFICIAL_EXPECTED_COLUMN_COUNT",
    "CoverageRegistryError",
    "build_coverage_registry",
    "validate_coverage_registry",
]
