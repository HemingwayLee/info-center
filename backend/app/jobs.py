"""Answers run as background jobs, so they keep going when the caller disconnects.

The chat UI, the public API (/api/v1) and MCP all start answers here. A job's events are kept while it runs, so
anyone can watch it from the start (the chat UI after a reload, or someone watching an integration's research),
and at most settings.max_concurrent_turns Claude Code processes run at once; the rest wait their turn.

Jobs live in this process only: a server restart ends them, and recover_interrupted() marks what was left
running as an error on the next startup.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select

from app import models, schemas
from app.answers import export_turn, split_references
from app.claude import research_prompt, run_turn
from app.config import settings
from app.db import SessionLocal

logger = logging.getLogger(__name__)

_slots = asyncio.Semaphore(settings.max_concurrent_turns)
_jobs: dict[int, "Job"] = {}  # turn id -> job, while it runs


class Answer:
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


class Job:
    def __init__(self, turn_id: int) -> None:
        self.turn_id = turn_id
        self.queued = True  # waiting for a free slot
        self.events: list[dict] = []
        self._listeners: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None

    def publish(self, event: dict | None) -> None:
        """Send an event to everyone watching; None ends their streams."""
        if event is not None:
            self.events.append(event)
        for queue in self._listeners:
            queue.put_nowait(event)

    async def watch(self) -> AsyncIterator[dict]:
        """Every event from the start, then new ones as they happen, until the job ends."""
        queue: asyncio.Queue = asyncio.Queue()
        backlog = list(self.events)  # no await between copying and subscribing, so nothing is missed
        self._listeners.add(queue)
        try:
            for event in backlog:
                yield event
            while (event := await queue.get()) is not None:
                yield event
        finally:
            self._listeners.discard(queue)


def _sources(db) -> list[tuple[str, int]]:
    return [(s.name, s.level) for s in db.scalars(select(models.Source).order_by(models.Source.id))]


class Busy(Exception):
    """The chat is still answering an earlier question."""


def start_turn(
    db,
    conversation: models.Conversation,
    question: str,
    research: bool,
    allowed_tools: list[str] | None = None,
) -> models.Turn:
    """Save the question and start answering it in the background. Returns the saved turn (status "running")."""
    if any(t.status == "running" for t in conversation.turns):
        raise Busy("This chat is still answering an earlier question")
    if not conversation.turns:
        conversation.title = question.strip().splitlines()[0][:80] or "New conversation"

    sources = _sources(db)
    research_text = None
    if research:
        by_level: dict[int, list[str]] = {}
        for name, level in sources:
            by_level.setdefault(level, []).append(name)
        research_text = research_prompt(by_level)

    # Saved before Claude runs, so the question is kept even if the answer fails.
    turn = models.Turn(
        conversation_id=conversation.id,
        question=question,
        model=conversation.model,
        mode="research" if research else "normal",
    )
    db.add(turn)
    db.commit()

    job = Job(turn.id)
    _jobs[turn.id] = job
    job.publish({"type": "turn", "turn_id": turn.id})
    job.task = asyncio.get_running_loop().create_task(
        _run(job, conversation.id, question, conversation.model, conversation.claude_session_id,
             research_text, allowed_tools, sources)
    )
    return turn


async def _run(job, conversation_id, question, model, resume, research_text, allowed_tools, sources) -> None:
    answer = Answer()
    session_id, cost, finished = resume, None, False
    try:
        async with _slots:
            job.queued = False
            async for event in run_turn(question, model, resume, research_text, allowed_tools):
                if event["type"] == "session":
                    session_id = event["session_id"] or session_id
                    continue
                if event["type"] == "result":
                    session_id = event["session_id"] or session_id
                    cost, finished = event["cost_usd"], True
                    if event["is_error"]:
                        answer.add({"type": "error", "text": event["result"] or event["subtype"]})
                answer.add(event)
                job.publish(event)
    except asyncio.CancelledError:
        pass  # Stop / cancel: keep the partial answer, saved as "stopped" below
    except Exception as exc:  # surface SDK/CLI failures to whoever is watching
        logger.exception("Claude turn failed")
        # The SDK also raises after an error result; don't report the same failure twice.
        if not answer.errors:
            answer.add({"type": "error", "text": str(exc)})
            job.publish({"type": "error", "text": str(exc)})
    finally:
        try:
            saved = _save(job.turn_id, conversation_id, answer, session_id, cost, finished, sources)
            if saved is not None:
                job.publish({"type": "saved", "turn": saved})
            job.publish({"type": "done"})
        finally:
            _jobs.pop(job.turn_id, None)
            job.publish(None)


def _save(turn_id, conversation_id, answer, session_id, cost, finished, sources) -> dict | None:
    annotated, references = split_references(answer.text)
    with SessionLocal() as session:
        row = session.get(models.Turn, turn_id)
        if row is None:  # the chat was deleted while answering
            return None
        row.activity = answer.activity
        row.error = "\n".join(answer.errors) or None
        row.status = "error" if answer.errors else "complete" if finished else "stopped"
        row.cost_usd = cost
        row.metadata_ = export_turn(row, annotated, references, sources)
        convo = session.get(models.Conversation, conversation_id)
        # Only resume from sessions that actually produced output; a turn that failed
        # before Claude responded may not have a transcript on disk.
        if convo is not None and (answer.text or answer.activity):
            convo.claude_session_id = session_id
        session.commit()
        return schemas.TurnRead.model_validate(row).model_dump(mode="json")


def get_job(turn_id: int) -> Job | None:
    return _jobs.get(turn_id)


def status_of(turn: models.Turn) -> str:
    """The turn's status, with "queued" for a job still waiting for a free slot."""
    job = _jobs.get(turn.id)
    return "queued" if job is not None and job.queued else turn.status


def cancel(turn_id: int) -> bool:
    """Stop a running answer; its partial text is saved as "stopped". False if it isn't running here."""
    job = _jobs.get(turn_id)
    if job is None or job.task is None or job.task.done():
        return False
    job.task.cancel()
    return True


async def watch(turn_id: int) -> AsyncIterator[dict[str, Any]]:
    """A running job's events from the start; for a finished turn, just its saved copy."""
    job = _jobs.get(turn_id)
    if job is not None:
        async for event in job.watch():
            yield event
        return
    with SessionLocal() as session:
        row = session.get(models.Turn, turn_id)
        if row is not None:
            yield {"type": "turn", "turn_id": row.id}
            yield {"type": "saved", "turn": schemas.TurnRead.model_validate(row).model_dump(mode="json")}
    yield {"type": "done"}


def recover_interrupted() -> int:
    """Mark answers left "running" by a previous server process as errors, so they can be read and exported."""
    with SessionLocal() as session:
        turns = session.scalars(select(models.Turn).where(models.Turn.status == "running")).all()
        if not turns:
            return 0
        sources = _sources(session)
        for turn in turns:
            turn.status = "error"
            turn.error = "Interrupted: the server restarted while this answer was being written"
            turn.metadata_ = export_turn(turn, "", [], sources)
        session.commit()
        return len(turns)


async def cancel_all() -> None:
    """On shutdown: stop running answers so their partial text is saved."""
    tasks = [job.task for job in list(_jobs.values()) if job.task is not None and not job.task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=10)
