from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Integration(Base):
    """Another system allowed to use this app (MCP or /api/v1), with its API key, permissions and limits."""

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[UUID] = mapped_column(
        Uuid, unique=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100))
    # SHA-256 of the API key; the key itself is shown once, when it's created.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(20))  # start of the key, to tell keys apart in the UI
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # What it may do: "research" (start and cancel research), "read" (get results, search past answers).
    scopes: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["research", "read"])
    daily_limit: Mapped[int | None] = mapped_column(Integer)  # questions per 24 hours; None = unlimited
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="integration")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable identifier for exports and other tools (ids are only meaningful inside this database).
    uuid: Mapped[UUID] = mapped_column(
        Uuid, unique=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    model: Mapped[str] = mapped_column(String(100))
    # Claude Code session id, used to resume the agent's context on the next turn.
    claude_session_id: Mapped[str | None] = mapped_column(String(100))
    # The integration that started this chat; None for chats from this app's own UI (or a deleted integration).
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Turn.id"
    )
    integration: Mapped[Integration | None] = relationship(back_populates="conversations")

    @property
    def integration_name(self) -> str | None:
        return self.integration.name if self.integration else None


class Turn(Base):
    """One question and Claude's answer, stored in the export format (see app/answers.py)."""

    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[UUID] = mapped_column(
        Uuid, unique=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    question: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(20))  # "normal" | "research" (Ref on)
    # Tool calls and results while answering: [{"type": "tool_use" | "tool_result", ...}]
    activity: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | complete | stopped | error
    # The answer, stored once as the full export JSON (answers.export_turn) when it's saved, and served as-is by
    # the export endpoints. The chat UI reads `content` (plain Markdown), `annotations` ([{"start", "end",
    # "cite": [n, ...] | "confidence": N}], code point offsets into content) and `references` ([{"n", "url",
    # "title", "publisher", "level"}], level being the Source list's rating when answered). NULL while running.
    # `metadata` is reserved on SQLAlchemy models, hence the attribute name `metadata_`.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float | None]

    conversation: Mapped[Conversation] = relationship(back_populates="turns")


class Source(Base):
    """A website or platform and its credibility level (1 = most credible, 4 = least)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Names are unique ignoring case ("BBC.com" and "bbc.com" are the same site).
Index("ix_sources_name_lower", func.lower(Source.name), unique=True)
