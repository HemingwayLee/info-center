from datetime import datetime
from typing import Any, Literal
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
    integration_name: str | None = None  # set for chats started by an integration
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
    # The stored export JSON (see models.Turn.metadata_); None while the answer is running.
    metadata: dict[str, Any] | None = Field(validation_alias="metadata_")
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


# ---- Integrations ------------------------------------------------------------------------------------------

Scope = Literal["research", "read"]


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(default_factory=lambda: ["research", "read"])
    daily_limit: int | None = Field(default=None, ge=1)

    _strip = field_validator("name")(_strip_name)


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    scopes: list[Scope] | None = None
    daily_limit: int | None = Field(default=None, ge=1)

    _strip = field_validator("name")(_strip_name)


class IntegrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    name: str
    key_prefix: str
    enabled: bool
    scopes: list[str]
    daily_limit: int | None
    created_at: datetime
    last_used_at: datetime | None
    # Usage, filled in by the list endpoint.
    questions_24h: int = 0
    questions_total: int = 0
    cost_usd_total: float | None = None


class IntegrationCreated(IntegrationRead):
    api_key: str  # shown once


# ---- Public API (/api/v1) ----------------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    # Answer like a research paper, citing sources for each claim (the UI's "Ref" toggle).
    research_mode: bool = True
    # Continue an earlier chat (its uuid); Claude keeps that chat's context. Omit to start a new chat.
    conversation_id: UUID | None = None
    model: str | None = None


class ResearchJob(BaseModel):
    job_id: UUID
    conversation_id: UUID
    question: str
    created_at: datetime
    # queued | running | stopping (just cancelled) | complete | stopped | error
    status: str
    error: str | None = None
    # The stored answer (turns.metadata, schema_version 2) once the job has finished.
    result: dict[str, Any] | None = None


class ResearchSummary(BaseModel):
    job_id: UUID
    conversation_id: UUID
    question: str
    created_at: datetime
    status: str
