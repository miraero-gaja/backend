"""Closed structured-query contracts for deterministic PostgreSQL retrieval."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FilterOperator(StrEnum):
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"
    GT = "GT"
    GE = "GE"


class SortDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class AggregateFunction(StrEnum):
    COUNT = "COUNT"


QueryScalar = str | int | float | bool | Decimal | date | datetime


class StructuredFilter(BaseModel):
    """One allowlisted comparison whose value will be bound, never interpolated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1)
    operator: FilterOperator
    value: QueryScalar

    @field_validator("field")
    @classmethod
    def reject_blank_field(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value


class StructuredSort(BaseModel):
    """The single deterministic user-requested sort supported by G2-B."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1)
    direction: SortDirection

    @field_validator("field")
    @classmethod
    def reject_blank_field(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value


class StructuredQueryContract(BaseModel):
    """A finite query plan; it intentionally contains no SQL text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_scope: str = Field(min_length=1)
    filters: tuple[StructuredFilter, ...] = Field(default=(), max_length=20)
    projections: tuple[str, ...] = Field(default=(), max_length=20)
    sort: StructuredSort | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    aggregate: AggregateFunction | None = None

    @field_validator("product_scope")
    @classmethod
    def reject_blank_scope(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("product_scope must not be blank")
        return value

    @field_validator("projections")
    @classmethod
    def validate_projections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("projection fields must not be blank")
        if len(set(values)) != len(values):
            raise ValueError("projection fields must be unique")
        return values

    @model_validator(mode="after")
    def validate_query_shape(self) -> StructuredQueryContract:
        if self.aggregate is AggregateFunction.COUNT:
            if self.projections:
                raise ValueError("COUNT cannot include row projections")
            if self.sort is not None:
                raise ValueError("COUNT cannot include row sorting")
            if self.limit is not None:
                raise ValueError("COUNT cannot include a row limit")
        elif not self.projections:
            raise ValueError("row queries require at least one projection")
        return self


__all__ = [
    "AggregateFunction",
    "FilterOperator",
    "QueryScalar",
    "SortDirection",
    "StructuredFilter",
    "StructuredQueryContract",
    "StructuredSort",
]
