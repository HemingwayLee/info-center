"""MCP server at /mcp (Streamable HTTP), so AI agents can use this app as a research tool.

Connecting is the standard MCP handshake: the client and server agree on a protocol version, the server sends
INSTRUCTIONS (how to use it), and tools/list returns the tools this caller may use, each with a description and
an input schema. Every request must carry an integration's key (`Authorization: Bearer <key>`); a missing,
wrong or disabled key gets HTTP 401 before MCP sees the request. The tools share their rules with /api/v1
(app/integrations.py).
"""

import json
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from app import integrations as svc
from app import models, schemas
from app.db import SessionLocal

INSTRUCTIONS = """\
info-center answers research questions with Claude, citing web sources, and rates each source's credibility.

Research takes a few minutes, so it runs in the background:
1. Call start_research with the question. It returns a job_id right away.
2. Call get_research with that job_id every 30-60 seconds until status is "complete", "stopped" or "error".
   "queued" means it's waiting for a free slot; "running" means it's being written.
3. The finished answer comes back as Markdown: [n] cites reference n in the References list (with the user's
   credibility level, Lv1 = most credible to Lv4 = least), and "(confidence: N%)" follows a claim the model
   made from its own knowledge, without a source. Pass format="json" for the structured form instead.

To ask a follow-up with the earlier answer as context, pass its conversation_id to start_research. Use
search_answers to find earlier research before starting a new job for the same question.
"""

# The permission each tool needs; tools/list only shows a caller the tools it may use.
TOOL_SCOPES = {
    "start_research": "research",
    "cancel_research": "research",
    "get_research": "read",
    "search_answers": "read",
}


def _caller(headers) -> models.Integration:
    integration = svc.authenticate_header((headers or {}).get("authorization"))
    if integration is None:
        raise ToolError("Missing, wrong or disabled API key")
    return integration


def _run(fn, *args):
    """Run a research function with its own session, turning refusals into tool errors."""
    with SessionLocal() as db:
        try:
            return fn(db, *args)
        except svc.Denied as exc:
            raise ToolError(exc.message) from None


async def _filter_tools(ctx, call_next):
    """Middleware: list only the tools the caller's permissions allow."""
    result = await call_next(ctx)
    if ctx.method != "tools/list":
        return result
    integration = svc.authenticate_header(getattr(getattr(ctx, "request", None), "headers", {}).get("authorization"))
    scopes = set(integration.scopes) if integration else set()
    allowed = lambda name: TOOL_SCOPES.get(name) in scopes  # noqa: E731
    if isinstance(result, BaseModel):
        return result.model_copy(update={"tools": [t for t in result.tools if allowed(t.name)]})
    if isinstance(result, dict):
        return {**result, "tools": [t for t in result.get("tools", []) if allowed(t.get("name"))]}
    return result


server = MCPServer(
    name="info-center",
    title="info-center research",
    instructions=INSTRUCTIONS,
    version="1",
    middleware=[_filter_tools],
)


def _job(turn: models.Turn, fmt: str = "markdown") -> dict[str, Any]:
    view = svc.job_view(turn).model_dump(mode="json", exclude={"result"})
    if turn.metadata_ is not None:
        if fmt == "json":
            view["result"] = turn.metadata_
        else:
            view["answer_markdown"] = svc.research_markdown(turn)
    else:
        view["check_again_in_seconds"] = 30
    return view


@server.tool(annotations=ToolAnnotations(title="Start research", openWorldHint=True))
async def start_research(
    question: str,
    ctx: Context,
    research_mode: bool = True,
    conversation_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Start researching a question in the background; returns a job_id right away.

    research_mode=True (default) answers like a research paper, citing a web source for each claim.
    conversation_id continues an earlier chat (from a previous result), so Claude has that context.
    model picks the Claude model (claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5, ...); omit for the default.
    Then call get_research with the job_id every 30-60 seconds; answers usually take 1-5 minutes.
    """
    integration = _caller(ctx.headers)
    try:
        request = schemas.ResearchRequest(
            question=question, research_mode=research_mode, conversation_id=conversation_id, model=model
        )
    except ValueError as exc:
        raise ToolError(f"Invalid arguments: {exc}") from None
    turn = _run(svc.start_research, integration, request)
    with SessionLocal() as db:
        return _job(db.get(models.Turn, turn.id))


@server.tool(annotations=ToolAnnotations(title="Get research", readOnlyHint=True))
async def get_research(job_id: str, ctx: Context, format: str = "markdown") -> dict[str, Any]:
    """Check a research job: its status and, once finished, the answer.

    status is "queued", "running", "complete", "stopped" (cancelled; partial answer) or "error".
    format="markdown" (default) returns answer_markdown: the answer with [n] citations, "(confidence: N%)" notes
    and a References list with credibility levels. format="json" returns `result`, the stored answer:
    `content` (Markdown), `annotations` ([{start, end, cite: [n] | confidence: N}], Unicode code point offsets
    into content) and `references`.
    """
    integration = _caller(ctx.headers)
    if format not in ("markdown", "json"):
        raise ToolError('format must be "markdown" or "json"')
    with SessionLocal() as db:
        try:
            return _job(svc.get_research(db, integration, job_id), format)
        except svc.Denied as exc:
            raise ToolError(exc.message) from None


@server.tool(annotations=ToolAnnotations(title="Search past answers", readOnlyHint=True))
async def search_answers(ctx: Context, query: str = "", limit: int = 10) -> dict[str, Any]:
    """Find this integration's earlier research, newest first; query matches the question or answer text.

    Returns job_id, conversation_id, question, created_at and status for each; use get_research for the answer.
    """
    integration = _caller(ctx.headers)
    with SessionLocal() as db:
        try:
            turns = svc.search_answers(db, integration, query, limit)
        except svc.Denied as exc:
            raise ToolError(exc.message) from None
        return {"answers": [svc.summary_view(t).model_dump(mode="json") for t in turns]}


@server.tool(annotations=ToolAnnotations(title="Cancel research", destructiveHint=False, idempotentHint=True))
async def cancel_research(job_id: str, ctx: Context) -> dict[str, Any]:
    """Stop a running research job. The partial answer is kept, with status "stopped"."""
    integration = _caller(ctx.headers)
    with SessionLocal() as db:
        try:
            turn = svc.cancel_research(db, integration, job_id)
        except svc.Denied as exc:
            raise ToolError(exc.message) from None
        return {"job_id": str(turn.uuid), "status": "stopping" if turn.status == "running" else turn.status}


class _RequireKey:
    """ASGI wrapper: reject requests without a valid, enabled integration key before MCP handles them."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/mcp" or path.startswith("/mcp/")):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            integration = await anyio.to_thread.run_sync(svc.authenticate_header, headers.get("authorization"))
            if integration is None:
                body = json.dumps({"error": "Missing, wrong or disabled API key", "auth": "Authorization: Bearer <key>"})
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
                })
                await send({"type": "http.response.body", "body": body.encode()})
                return
        await self.app(scope, receive, send)


def asgi_app():
    """The /mcp endpoint. Stateless (each request stands alone), so it needs no sticky sessions behind a proxy."""
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",  # not localhost-only: other systems connect to it
    )
    return _RequireKey(app)
