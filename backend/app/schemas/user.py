import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMSchema


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str | None = Field(default=None, max_length=255)


class UserRead(ORMSchema):
    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
