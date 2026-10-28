"""
DataJanitor — Pydantic schemas for dataset upload, profile and preview.
"""

from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

StatValue = Union[int, float, str, None]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Standard error body returned for every handled failure."""
    error: ErrorDetail


class ColumnProfile(BaseModel):
    """Per-column metadata and basic statistics."""
    name: str
    inferred_type: str = Field(
        description="integer | float | boolean | datetime | text | mixed | empty"
    )
    non_null_count: int
    missing_count: int
    missing_percent: float
    unique_count: int
    parse_ratio: Optional[float] = Field(
        default=None,
        description="Share of non-missing values that parse as the dominant "
        "numeric/date type. Below 1.0 means some values did not fit.",
    )
    stats: Dict[str, StatValue] = Field(default_factory=dict)


class PreviewRow(BaseModel):
    """One data row. `row_number` is the stable 1-based data-row index."""
    row_number: int
    values: Dict[str, Optional[str]]


class DatasetPreview(BaseModel):
    columns: List[str]
    rows: List[PreviewRow]
    preview_row_count: int


class UploadResponse(BaseModel):
    dataset_id: str
    filename: str
    size_bytes: int
    encoding: str
    delimiter: str
    row_count: int
    column_count: int
    uploaded_at: datetime
    columns: List[ColumnProfile]
    preview: DatasetPreview
    warnings: List[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    """Profile + a page of rows for an already-uploaded dataset (re-read from the stored original)."""
    dataset_id: str
    filename: str
    row_count: int
    column_count: int
    encoding: str
    delimiter: str
    columns: List[ColumnProfile]
    preview: DatasetPreview
    preview_offset: int
    preview_limit: int
    warnings: List[str] = Field(default_factory=list)
