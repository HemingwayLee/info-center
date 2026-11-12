import json
import logging
from typing import Literal
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, selectinload

from app import jobs, mcp_server, models, schemas
from app.answers import SCHEMA_VERSION, export_markdown, export_turn, upgrade_export
from app.api_v1 import api as api_v1
from app.claude import MODELS
from app.config import settings
from app.db import Base, SessionLocal, engine, get_db
from app.integrations import router as integrations_router
from app.sources import router as sources_router, seed_sources

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev convenience: create tables on startup. Swap for Alembic migrations later.
    Base.metadata.create_all(bind=engine)
    _migrate_turns()
    _migrate_exports()
    _migrate_conversations()
    seed_sources()
    if count := jobs.recover_interrupted():
        logger.warning("Marked %d answers interrupted by a restart as errors", count)
    async with mcp_server.server.session_manager.run():
        yield
        await jobs.cancel_all()  # save partial answers of anything still running


def _migrate_turns() -> None:
    """Bring an older turns table up to date. Idempotent; a no-op on an up-to-date table.

    Older tables kept the answer in `content` and its references in `references` (an array) or `additional`
    ({"references": [...]}). This adds `metadata`, fills it from those for saved answers, then drops them.
    """
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE turns ADD COLUMN IF NOT EXISTS metadata JSON"))
        columns = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'turns'"
                )
            ).scalars()
        )
        old = [c for c in ("content", "additional", "references") if c in columns]
        if not old:
            return
        refs_sql = (
            "additional->'references'" if "additional" in columns else '"references"' if "references" in columns
            else "NULL"
        )
        content_sql = "content" if "content" in columns else "''"
        rows = conn.execute(
            text(f"SELECT id, {content_sql}, {refs_sql} FROM turns WHERE metadata IS NULL AND status <> 'running'")
        ).all()
        if rows:
            # Build each answer's metadata from its old columns and the ORM row for everything else.
            with SessionLocal(bind=conn) as session:
                sources = _sources(session)
                for turn_id, content, references in rows:
                    turn = session.get(models.Turn, turn_id)
                    payload = export_turn(turn, content or "", references or [], sources)
                    conn.execute(
                        text("UPDATE turns SET metadata = CAST(:m AS JSON) WHERE id = :id"),
                        {"m": json.dumps(payload), "id": turn_id},
                    )
        for column in old:
            conn.execute(text(f'ALTER TABLE turns DROP COLUMN "{column}"'))
        logger.info("Migrated turns: filled metadata for %d answers, dropped %s", len(rows), ", ".join(old))


def _migrate_exports() -> None:
    """Upgrade stored exports to the current schema_version (answers.upgrade_export). Idempotent."""
    with SessionLocal() as session:
        turns = session.scalars(
            select(models.Turn).where(
                models.Turn.metadata_.is_not(None),
                text("COALESCE((metadata->>'schema_version')::int, 1) < :v").bindparams(v=SCHEMA_VERSION),
            )
        ).all()
        for turn in turns:
            turn.metadata_ = upgrade_export(turn.metadata_)
        if turns:
            session.commit()
            logger.info("Upgraded %d stored exports to schema_version %d", len(turns), SCHEMA_VERSION)


def _migrate_conversations() -> None:
    """Add conversations.integration_id to tables created before integrations existed. Idempotent."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS integration_id INTEGER "
                "REFERENCES integrations(id) ON DELETE SET NULL"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_conversations_integration_id ON conversations (integration_id)")
        )


# Built at import so its session manager exists when the lifespan starts it.
_mcp_app = mcp_server.asgi_app()

app = FastAPI(title="info-center API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources_router)
app.include_router(integrations_router)
app.mount("/api/v1", api_v1)  # public API for other systems, with its own docs at /api/v1/docs


def _get_conversation(db: Session, conversation_id: int) -> models.Conversation:
    conversation = db.get(models.Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/api/models")
def list_models():
    return {"models": MODELS, "default": settings.claude_default_model}


@app.get("/api/prompts/history")
def prompt_history(limit: int = 200, db: Session = Depends(get_db)):
    """Recently sent prompts across all chats, newest first, for Up/Down recall in the composer."""
    stmt = select(models.Turn.question).order_by(models.Turn.id.desc()).limit(min(max(limit, 1), 1000))
    prompts: list[str] = []
    for question in db.scalars(stmt):
        if question and (not prompts or prompts[-1] != question):  # drop consecutive repeats
            prompts.append(question)
    return prompts


@app.get("/api/conversations", response_model=list[schemas.ConversationRead])
def list_conversations(db: Session = Depends(get_db)):
    stmt = (
        select(models.Conversation)
        .options(selectinload(models.Conversation.integration))
        .order_by(models.Conversation.updated_at.desc())
    )
    return db.scalars(stmt).all()


@app.post("/api/conversations", response_model=schemas.ConversationRead, status_code=201)
def create_conversation(payload: schemas.ConversationCreate, db: Session = Depends(get_db)):
    conversation = models.Conversation(model=payload.model or settings.claude_default_model)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=schemas.ConversationDetail)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    return _get_conversation(db, conversation_id)


@app.patch("/api/conversations/{conversation_id}", response_model=schemas.ConversationRead)
def update_conversation(
    conversation_id: int, payload: schemas.ConversationUpdate, db: Session = Depends(get_db)
):
    conversation = _get_conversation(db, conversation_id)
    data = payload.model_dump(exclude_unset=True)
    if data:
        # Setting updated_at to itself skips its onupdate, so renaming doesn't reorder the chat list.
        db.execute(
            update(models.Conversation)
            .where(models.Conversation.id == conversation_id)
            .values(**data, updated_at=models.Conversation.updated_at)
        )
        if "title" in data:
            # Keep the chat title in each answer's stored export current.
            for turn in conversation.turns:
                if turn.metadata_ is not None:
                    turn.metadata_ = {
                        **turn.metadata_,
                        "conversation": {**turn.metadata_["conversation"], "title": data["title"]},
                    }
        db.commit()
        db.refresh(conversation)
    return conversation


@app.delete("/api/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    for turn in conversation.turns:  # stop an answer still being written; there's nowhere to save it
        if turn.status == "running":
            jobs.cancel(turn.id)
    db.delete(conversation)
    db.commit()


def _sources(db: Session) -> list[tuple[str, int]]:
    return [(s.name, s.level) for s in db.scalars(select(models.Source).order_by(models.Source.id))]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _event_stream(turn_id: int) -> StreamingResponse:
    """Server-sent events for an answer, from its start. Disconnecting stops the stream, not the answer."""

    async def stream():
        async for event in jobs.watch(turn_id):
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Async because it starts a background job on the event loop.
@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, payload: schemas.ChatRequest, db: Session = Depends(get_db)):
    """Ask a question in a chat and stream the answer. The first event is {"type": "turn", "turn_id"}."""
    conversation = _get_conversation(db, conversation_id)
    try:
        turn = jobs.start_turn(db, conversation, payload.content, payload.research)
    except jobs.Busy as exc:
        raise HTTPException(409, str(exc)) from None
    return _event_stream(turn.id)


@app.get("/api/turns/{turn_id}/stream")
def watch_turn(turn_id: int, db: Session = Depends(get_db)):
    """Watch an answer from its start: a running one live, a finished one as its saved copy."""
    if db.get(models.Turn, turn_id) is None:
        raise HTTPException(404, "Answer not found")
    return _event_stream(turn_id)


@app.post("/api/turns/{turn_id}/cancel", status_code=202)
async def cancel_turn(turn_id: int, db: Session = Depends(get_db)):
    """Stop a running answer (the Stop button). The partial answer is saved as "stopped"."""
    turn = db.get(models.Turn, turn_id)
    if turn is None:
        raise HTTPException(404, "Answer not found")
    return {"stopping": jobs.cancel(turn_id), "status": turn.status}


def _find(db: Session, model, ref: str, label: str):
    """Look a row up by numeric id or by UUID."""
    if ref.isdigit():
        row = db.get(model, int(ref))
    else:
        try:
            row = db.scalars(select(model).where(model.uuid == UUID(ref))).first()
        except ValueError:
            row = None
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return row


def _stored_export(turn: models.Turn) -> dict:
    """The export JSON saved in turns.metadata when the answer finished."""
    if turn.metadata_ is None:
        raise HTTPException(409, "This answer is still being written; export it once it finishes")
    return turn.metadata_


@app.get("/api/turns/{turn_ref}/export")
def export_turn_endpoint(
    turn_ref: str,
    format: Literal["json", "markdown"] = "json",
    download: bool = False,
    db: Session = Depends(get_db),
):
    """One question and answer (by id or UUID) in the portable format: JSON, or Markdown for another LLM."""
    turn = _find(db, models.Turn, turn_ref, "Answer")
    data = _stored_export(turn)
    disposition = {"Content-Disposition": f'attachment; filename="answer-{turn.uuid}.{"json" if format == "json" else "md"}"'}
    headers = disposition if download else {}
    if format == "markdown":
        return PlainTextResponse(export_markdown(data), media_type="text/markdown; charset=utf-8", headers=headers)
    return JSONResponse(data, headers=headers)


@app.get("/api/conversations/{conversation_ref}/export")
def export_conversation(conversation_ref: str, db: Session = Depends(get_db)):
    """Every answer in a chat (by id or UUID), oldest first, in the same format as /api/turns/{id}/export."""
    conversation = _find(db, models.Conversation, conversation_ref, "Conversation")
    # Answers still being written have no export yet.
    return [turn.metadata_ for turn in conversation.turns if turn.metadata_ is not None]


# MCP for AI agents (Streamable HTTP at /mcp). Mounted last: its app only routes /mcp, everything else 404s.
app.mount("/", _mcp_app)
