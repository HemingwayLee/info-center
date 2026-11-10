from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreate(BaseModel):
    model: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    title: str
    model: str
    created_at: datetime
    updated_at: datetime


class TurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    schema_version: int
    question: str
    created_at: datetime
    model: str
    mode: str
    content: str
    references: list[dict[str, Any]]
    activity: list[dict[str, Any]]
    status: str
    error: str | None
    cost_usd: float | None


class ConversationDetail(ConversationRead):
    turns: list[TurnRead]


class ChatRequest(BaseModel):
    content: str = Field(min_length=1)
    # "Ref" toggle: answer like a research paper, citing sources for each claim.
    research: bool = False


def _strip_name(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("Name can't be blank")
    return v


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    level: int

    _strip = field_validator("name")(_strip_name)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    level: int | None = None

    _strip = field_validator("name")(_strip_name)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level: int
