import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMSchema


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    owner_id: uuid.UUID | None = None


class ProjectRead(ORMSchema):
    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
