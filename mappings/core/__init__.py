"""Priority A semantic field allowlist for deterministic structured queries."""

from .registry import (
    ALLOWED_OPERATIONS,
    CORE_FIELD_MAPPINGS,
    OFFICIAL_COLUMN_COUNT,
    OFFICIAL_TABLE_COLUMN_COUNTS,
    CoreFieldMapping,
    CoreUnitStatus,
    SemanticStatus,
    build_core_field_registry,
    get_confirmed_core_fields,
    get_confirmed_field_map,
    get_core_mapping_summary,
    validate_core_field_registry,
)

__all__ = [
    "ALLOWED_OPERATIONS",
    "CORE_FIELD_MAPPINGS",
    "CoreFieldMapping",
    "CoreUnitStatus",
    "OFFICIAL_COLUMN_COUNT",
    "OFFICIAL_TABLE_COLUMN_COUNTS",
    "SemanticStatus",
    "build_core_field_registry",
    "get_confirmed_core_fields",
    "get_confirmed_field_map",
    "get_core_mapping_summary",
    "validate_core_field_registry",
]
