"""Integrations: other systems that use this app through MCP (/mcp) or the public API (/api/v1).

Each integration has an API key (sent as `Authorization: Bearer <key>`), permissions ("research" to start and
cancel research, "read" to get results and search past answers) and an optional daily question limit. Turning
one off, or deleting it, cuts it off at once. The research functions here are shared by MCP and /api/v1, so
both apply the same rules: an integration only sees its own chats, and Claude only gets research tools.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import jobs, models, schemas
from app.answers import export_markdown
from app.claude import MODELS
from app.config import settings
from app.db import SessionLocal, get_db

KEY_PREFIX = "ic_"
SCOPES = ("research", "read")


# ---- Keys ----------------------------------------------------------------------------------------------


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _new_key() -> tuple[str, str, str]:
    """(key, its hash, a display prefix)."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, _hash(key), key[:10]


def bearer_key(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def authenticate(db: Session, key: str | None) -> models.Integration | None:
    """The enabled integration this key belongs to (and note that it was used), or None."""
    if not key:
        return None
    integration = db.scalars(select(models.Integration).where(models.Integration.key_hash == _hash(key))).first()
    if integration is None or not integration.enabled:
        return None
    integration.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return integration


def authenticate_header(authorization: str | None) -> models.Integration | None:
    """authenticate() with its own session, for callers outside a FastAPI request (MCP)."""
    with SessionLocal(expire_on_commit=False) as db:
        return authenticate(db, bearer_key(authorization))


# ---- Research (shared by MCP and /api/v1) --------------------------------------------------------------


class Denied(Exception):
    """A request the integration isn't allowed to make; `status` is the matching HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def require(integration: models.Integration, scope: str) -> None:
    if scope not in integration.scopes:
        raise Denied(403, f'This integration doesn\'t have the "{scope}" permission')


def _own_conversation(db: Session, integration: models.Integration, ref: UUID) -> models.Conversation:
    conversation = db.scalars(select(models.Conversation).where(models.Conversation.uuid == ref)).first()
    if conversation is None or conversation.integration_id != integration.id:
        raise Denied(404, "Conversation not found")
    return conversation


def _own_turn(db: Session, integration: models.Integration, job_id: UUID | str) -> models.Turn:
    try:
        ref = job_id if isinstance(job_id, UUID) else UUID(str(job_id))
    except ValueError:
        raise Denied(404, "Research job not found") from None
    turn = db.scalars(select(models.Turn).where(models.Turn.uuid == ref)).first()
    if turn is None or turn.conversation.integration_id != integration.id:
        raise Denied(404, "Research job not found")
    return turn


def _questions_since(db: Session, integration_id: int, since: datetime) -> int:
    stmt = (
        select(func.count(models.Turn.id))
        .join(models.Conversation)
        .where(models.Conversation.integration_id == integration_id, models.Turn.created_at >= since)
    )
    return db.scalar(stmt) or 0


def job_view(turn: models.Turn) -> schemas.ResearchJob:
    return schemas.ResearchJob(
        job_id=turn.uuid,
        conversation_id=turn.conversation.uuid,
        question=turn.question,
        created_at=turn.created_at,
        status=jobs.status_of(turn),
        error=turn.error,
        result=turn.metadata_,
    )


def start_research(db: Session, integration: models.Integration, request: schemas.ResearchRequest) -> models.Turn:
    require(integration, "research")
    if integration.daily_limit is not None:
        used = _questions_since(db, integration.id, datetime.now(timezone.utc) - timedelta(hours=24))
        if used >= integration.daily_limit:
            raise Denied(429, f"Daily limit reached ({integration.daily_limit} questions per 24 hours)")
    if request.model is not None and request.model not in {m["id"] for m in MODELS}:
        raise Denied(422, f"Unknown model; use one of {[m['id'] for m in MODELS]}")

    if request.conversation_id is not None:
        conversation = _own_conversation(db, integration, request.conversation_id)
    else:
        conversation = models.Conversation(
            model=request.model or settings.claude_default_model, integration_id=integration.id
        )
        db.add(conversation)
        db.flush()
    if request.model is not None:
        conversation.model = request.model
    try:
        return jobs.start_turn(
            db, conversation, request.question, request.research_mode, settings.integration_allowed_tools
        )
    except jobs.Busy as exc:
        raise Denied(409, f"{exc}; wait for it to finish or cancel it") from None


def get_research(db: Session, integration: models.Integration, job_id: UUID | str) -> models.Turn:
    require(integration, "read")
    return _own_turn(db, integration, job_id)


def research_markdown(turn: models.Turn) -> str | None:
    """A finished answer as Markdown with [n] citations, confidence notes and references, for LLMs."""
    return export_markdown(turn.metadata_) if turn.metadata_ is not None else None


def cancel_research(db: Session, integration: models.Integration, job_id: UUID | str) -> models.Turn:
    require(integration, "research")
    turn = _own_turn(db, integration, job_id)
    if turn.status == "running" and not jobs.cancel(turn.id):
        raise Denied(409, "This job isn't running in this server process")
    return turn


def search_answers(db: Session, integration: models.Integration, query: str, limit: int) -> list[models.Turn]:
    """The integration's questions, newest first; `query` matches the question or answer text."""
    require(integration, "read")
    stmt = (
        select(models.Turn)
        .join(models.Conversation)
        .where(models.Conversation.integration_id == integration.id)
        .order_by(models.Turn.id.desc())
        .limit(min(max(limit, 1), 100))
    )
    if query.strip():
        pattern = f"%{query.strip()}%"
        content = models.Turn.metadata_["content"].as_string()
        stmt = stmt.where(models.Turn.question.ilike(pattern) | content.ilike(pattern))
    return list(db.scalars(stmt))


def summary_view(turn: models.Turn) -> schemas.ResearchSummary:
    return schemas.ResearchSummary(
        job_id=turn.uuid,
        conversation_id=turn.conversation.uuid,
        question=turn.question,
        created_at=turn.created_at,
        status=jobs.status_of(turn),
    )


# ---- Admin endpoints (this app's own UI: the Integrations tab) -----------------------------------------

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def connection_info() -> dict:
    base = settings.public_base_url.rstrip("/")
    return {
        "mcp_url": f"{base}/mcp",
        "api_url": f"{base}/api/v1",
        "docs_url": f"{base}/api/v1/docs",
        "auth": "Authorization: Bearer <API key>",
        "allowed_tools": settings.integration_allowed_tools,
    }


def _get(db: Session, integration_id: int) -> models.Integration:
    integration = db.get(models.Integration, integration_id)
    if integration is None:
        raise HTTPException(404, "Integration not found")
    return integration


def _with_usage(db: Session, integration: models.Integration) -> dict:
    data = schemas.IntegrationRead.model_validate(integration).model_dump()
    totals = db.execute(
        select(func.count(models.Turn.id), func.sum(models.Turn.cost_usd))
        .join(models.Conversation)
        .where(models.Conversation.integration_id == integration.id)
    ).one()
    data["questions_total"], data["cost_usd_total"] = totals[0] or 0, totals[1]
    data["questions_24h"] = _questions_since(db, integration.id, datetime.now(timezone.utc) - timedelta(hours=24))
    return data


@router.get("/connection")
def get_connection_info():
    return connection_info()


@router.get("", response_model=list[schemas.IntegrationRead])
def list_integrations(db: Session = Depends(get_db)):
    return [_with_usage(db, i) for i in db.scalars(select(models.Integration).order_by(models.Integration.id))]


@router.post("", response_model=schemas.IntegrationCreated, status_code=201)
def create_integration(payload: schemas.IntegrationCreate, db: Session = Depends(get_db)):
    key, key_hash, prefix = _new_key()
    integration = models.Integration(
        name=payload.name,
        key_hash=key_hash,
        key_prefix=prefix,
        scopes=sorted(set(payload.scopes)),
        daily_limit=payload.daily_limit,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return {**_with_usage(db, integration), "api_key": key}


@router.patch("/{integration_id}", response_model=schemas.IntegrationRead)
def update_integration(integration_id: int, payload: schemas.IntegrationUpdate, db: Session = Depends(get_db)):
    integration = _get(db, integration_id)
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "enabled", "scopes"):
        if data.get(field) is None:
            data.pop(field, None)  # these can't be cleared
    if "scopes" in data:
        data["scopes"] = sorted(set(data["scopes"]))
    for field, value in data.items():
        setattr(integration, field, value)
    db.commit()
    db.refresh(integration)
    return _with_usage(db, integration)


@router.post("/{integration_id}/rotate-key", response_model=schemas.IntegrationCreated)
def rotate_key(integration_id: int, db: Session = Depends(get_db)):
    """Replace the API key; the old one stops working at once."""
    integration = _get(db, integration_id)
    key, integration.key_hash, integration.key_prefix = _new_key()
    db.commit()
    db.refresh(integration)
    return {**_with_usage(db, integration), "api_key": key}


@router.delete("/{integration_id}", status_code=204)
def delete_integration(integration_id: int, db: Session = Depends(get_db)):
    """Revoke and remove an integration. Its chats are kept, as ordinary chats."""
    db.delete(_get(db, integration_id))
    db.commit()
