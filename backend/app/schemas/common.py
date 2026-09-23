from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMSchema(BaseModel):
    """Base for response schemas built from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class Page[ItemT](BaseModel):
    """A page of results from a list endpoint."""

    items: list[ItemT]
    total: int = Field(ge=0, description="Total number of matching items.")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str
    timestamp: datetime


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, Literal["ok", "error"]]
