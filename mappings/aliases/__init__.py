"""Small, explicit natural-language aliases for deterministic grounding."""

from .registry import (
    FieldAlias,
    ProductAlias,
    field_alias_matches,
    normalize_alias_text,
    product_alias_matches,
)

__all__ = [
    "FieldAlias",
    "ProductAlias",
    "field_alias_matches",
    "normalize_alias_text",
    "product_alias_matches",
]
