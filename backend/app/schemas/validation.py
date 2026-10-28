"""
DataJanitor — schemas for configurable validation rules (Phase 4).

A `RuleSet` is plain JSON supplied by the user (or suggested from the data).
It is translated into a Pandera `DataFrameSchema` by validation_service.
"""

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_REGEX_LENGTH = 200


class ColumnRule(BaseModel):
    """Constraints for one column. Unset fields mean 'no constraint'."""

    column: str = Field(min_length=1, max_length=200)
    dtype: Optional[Literal["integer", "float", "date", "boolean", "string"]] = None
    nullable: bool = True
    unique: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    allowed_values: Optional[List[str]] = Field(default=None, max_length=500)
    regex: Optional[str] = Field(default=None, max_length=MAX_REGEX_LENGTH)

    @field_validator("regex")
    @classmethod
    def _regex_compiles(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"invalid regular expression: {exc}") from exc
        return v

    @model_validator(mode="after")
    def _ranges_consistent(self) -> "ColumnRule":
        if None not in (self.min_value, self.max_value) and self.min_value > self.max_value:
            raise ValueError("min_value cannot exceed max_value")
        if None not in (self.min_length, self.max_length) and self.min_length > self.max_length:
            raise ValueError("min_length cannot exceed max_length")
        if (self.min_value is not None or self.max_value is not None) and self.dtype not in (
            "integer", "float",
        ):
            raise ValueError("min_value/max_value require dtype 'integer' or 'float'")
        return self


class RuleSet(BaseModel):
    rules: List[ColumnRule] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _unique_columns(self) -> "RuleSet":
        names = [r.column for r in self.rules]
        if len(names) != len(set(names)):
            raise ValueError("each column may have at most one rule")
        return self


class RuleViolation(BaseModel):
    """One cell (or column) that breaks a validation rule."""

    column: Optional[str]
    row_number: Optional[int] = Field(description="1-based data row; null for column-level")
    rule: str = Field(description="Human-readable description of the failed rule")
    observed_value: Optional[str] = None


class ValidationSummary(BaseModel):
    ran: bool
    rule_count: int = 0
    violation_count: int = 0
    by_column: dict = Field(default_factory=dict)
    violations_sample: List[RuleViolation] = Field(default_factory=list)
