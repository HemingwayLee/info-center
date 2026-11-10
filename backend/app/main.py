import json
import logging
from typing import Literal
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.answers import export_markdown, export_turn, split_references, with_levels
from app.claude import MODELS, research_prompt, run_turn
from app.config import settings
from app.db import Base, SessionLocal, engine, get_db
from app.sources import router as sources_router, seed_sources

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev convenience: create tables on startup. Swap for Alembic migrations later.
    Base.metadata.create_all(bind=engine)
    seed_sources()
    yield


app = FastAPI(title="info-center API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources_router)


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
    stmt = select(models.Conversation).order_by(models.Conversation.updated_at.desc())
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
        db.commit()
        db.refresh(conversation)
    return conversation


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    db.delete(_get_conversation(db, conversation_id))
    db.commit()


def _sources(db: Session) -> list[tuple[str, int]]:
    return [(s.name, s.level) for s in db.scalars(select(models.Source).order_by(models.Source.id))]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


class _Answer:
    """Folds streamed events into the answer being written (mirrors applyEvent in frontend/src/api.js)."""

    def __init__(self) -> None:
        self.text = ""
        self.activity: list[dict] = []
        self.errors: list[str] = []
        self.new_message = False

    def add(self, event: dict) -> None:
        kind = event["type"]
        if kind == "text":
            # Text from consecutive assistant messages (e.g. before and after a tool call) is new paragraphs.
            if self.new_message and self.text and not self.text.endswith("\n\n"):
                self.text = self.text.rstrip("\n") + "\n\n"
            self.new_message = False
            self.text += event["text"]
        elif kind == "message_start":
            self.new_message = True
        elif kind in ("tool_use", "tool_result"):
            self.activity.append({k: v for k, v in event.items()})
        elif kind == "error":
            self.errors.append(event["text"])


@app.post("/api/conversations/{conversation_id}/messages")
def send_message(conversation_id: int, payload: schemas.ChatRequest, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    if not conversation.turns:
        conversation.title = payload.content.strip().splitlines()[0][:80] or "New chat"

    sources = _sources(db)
    research = None
    if payload.research:
        sources_by_level: dict[int, list[str]] = {}
        for name, level in sources:
            sources_by_level.setdefault(level, []).append(name)
        research = research_prompt(sources_by_level)

    # Saved before Claude runs, so the question is kept even if the answer fails.
    turn = models.Turn(
        conversation_id=conversation.id,
        question=payload.content,
        model=conversation.model,
        mode="research" if payload.research else "normal",
    )
    db.add(turn)
    db.commit()
    turn_id, model, resume = turn.id, conversation.model, conversation.claude_session_id

    async def stream():
        answer = _Answer()
        session_id, cost, finished = resume, None, False
        saved = None
        try:
            async for event in run_turn(payload.content, model, resume, research):
                if event["type"] == "session":
                    session_id = event["session_id"] or session_id
                    continue
                if event["type"] == "result":
                    session_id = event["session_id"] or session_id
                    cost, finished = event["cost_usd"], True
                    if event["is_error"]:
                        answer.add({"type": "error", "text": event["result"] or event["subtype"]})
                answer.add(event)
                yield _sse(event)
        except Exception as exc:  # surface SDK/CLI failures to the UI
            logger.exception("Claude turn failed")
            # The SDK also raises after an error result; don't report the same failure twice.
            if not answer.errors:
                answer.add({"type": "error", "text": str(exc)})
                yield _sse({"type": "error", "text": str(exc)})
        finally:
            # Runs on completion, error, and client abort (Stop button), so partial answers are kept.
            content, references = split_references(answer.text)
            with SessionLocal() as session:
                row = session.get(models.Turn, turn_id)
                if row is not None:
                    row.content = content
                    row.references = with_levels(references, sources)
                    row.activity = answer.activity
                    row.error = "\n".join(answer.errors) or None
                    row.status = "error" if answer.errors else "complete" if finished else "stopped"
                    row.cost_usd = cost
                    convo = session.get(models.Conversation, conversation_id)
                    # Only resume from sessions that actually produced output; a turn that failed
                    # before Claude responded may not have a transcript on disk.
                    if convo is not None and (answer.text or answer.activity):
                        convo.claude_session_id = session_id
                    session.commit()
                    saved = schemas.TurnRead.model_validate(row).model_dump(mode="json")
        if saved is not None:
            yield _sse({"type": "saved", "turn": saved})
        yield _sse({"type": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@app.get("/api/turns/{turn_ref}/export")
def export_turn_endpoint(
    turn_ref: str,
    format: Literal["json", "markdown"] = "json",
    download: bool = False,
    db: Session = Depends(get_db),
):
    """One question and answer (by id or UUID) in the portable format: JSON, or Markdown for another LLM."""
    turn = _find(db, models.Turn, turn_ref, "Answer")
    data = export_turn(turn, _sources(db))
    disposition = {"Content-Disposition": f'attachment; filename="answer-{turn.uuid}.{"json" if format == "json" else "md"}"'}
    headers = disposition if download else {}
    if format == "markdown":
        return PlainTextResponse(export_markdown(data), media_type="text/markdown; charset=utf-8", headers=headers)
    return JSONResponse(data, headers=headers)


@app.get("/api/conversations/{conversation_ref}/export")
def export_conversation(conversation_ref: str, db: Session = Depends(get_db)):
    """Every answer in a chat (by id or UUID), oldest first, in the same format as /api/turns/{id}/export."""
    conversation = _find(db, models.Conversation, conversation_ref, "Conversation")
    sources = _sources(db)
    return [export_turn(turn, sources) for turn in conversation.turns]
