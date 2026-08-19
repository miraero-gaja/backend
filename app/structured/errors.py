"""Typed failures raised before a structured query reaches PostgreSQL."""


class StructuredQueryError(ValueError):
    """Base class for deterministic structured-query failures."""


class StructuredQueryValidationError(StructuredQueryError):
    """Raised when a query violates the trusted field or type contract."""


class StructuredRegistryError(StructuredQueryError):
    """Raised when trusted registry configuration is ambiguous or unsafe."""


__all__ = [
    "StructuredQueryError",
    "StructuredQueryValidationError",
    "StructuredRegistryError",
]
