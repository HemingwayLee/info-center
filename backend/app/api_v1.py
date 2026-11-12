"""The public API for other systems, mounted at /api/v1 with its own docs (/api/v1/docs).

Everything except the welcome endpoint needs an integration's key: `Authorization: Bearer <key>`. Research
runs in the background: start a job, then poll it (answers take a few minutes). AI agents can use the same
features through MCP at /mcp.
"""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import integrations as svc
from app import models, schemas
from app.answers import SCHEMA_VERSION
from app.db import get_db

api = FastAPI(
    title="info-center public API",
    version="1",
    description=__doc__,
)  # its own /docs and /openapi.json, listing only these endpoints, not the UI's internal ones

_bearer = HTTPBearer(auto_error=False, description="An integration's API key, from the Integrations tab")


def integration(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> models.Integration:
    found = svc.authenticate(db, credentials.credentials if credentials else None)
    if found is None:
        raise HTTPException(401, "Missing, wrong or disabled API key", headers={"WWW-Authenticate": "Bearer"})
    return found


def _call(fn, *args):
    try:
        return fn(*args)
    except svc.Denied as exc:
        raise HTTPException(exc.status, exc.message) from None


@api.get("/", summary="Welcome: what this API is and how to connect (no key needed)")
def welcome():
    return {
        "name": "info-center",
        "api_version": 1,
        "result_schema_version": SCHEMA_VERSION,
        **svc.connection_info(),
        "endpoints": {
            "start research": "POST /api/v1/research",
            "get a job": "GET /api/v1/research/{job_id}",
            "get a job as Markdown": "GET /api/v1/research/{job_id}/markdown",
            "cancel a job": "POST /api/v1/research/{job_id}/cancel",
            "search past answers": "GET /api/v1/answers?q=",
        },
    }


# Starting and cancelling touch the job runner, which lives on the event loop: these two are async.
@api.post("/research", response_model=schemas.ResearchJob, status_code=202, summary="Start research")
async def start_research(
    payload: schemas.ResearchRequest,
    who: models.Integration = Depends(integration),
    db: Session = Depends(get_db),
):
    """Start answering a question in the background. Poll GET /research/{job_id} every 30-60 seconds."""
    return svc.job_view(_call(svc.start_research, db, who, payload))


@api.get("/research/{job_id}", response_model=schemas.ResearchJob, summary="Get a research job")
def get_research(job_id: str, who: models.Integration = Depends(integration), db: Session = Depends(get_db)):
    """The job's status; `result` holds the stored answer (schema_version 2) once it has finished."""
    return svc.job_view(_call(svc.get_research, db, who, job_id))


@api.get(
    "/research/{job_id}/markdown",
    response_class=PlainTextResponse,
    summary="Get a finished answer as Markdown",
    responses={409: {"description": "Still running"}},
)
def get_research_markdown(job_id: str, who: models.Integration = Depends(integration), db: Session = Depends(get_db)):
    """The answer with [n] citations, (confidence: N%) notes and its references, ready for an LLM."""
    text = svc.research_markdown(_call(svc.get_research, db, who, job_id))
    if text is None:
        raise HTTPException(409, "Still running; try again shortly")
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


@api.post("/research/{job_id}/cancel", response_model=schemas.ResearchJob, summary="Cancel a research job")
async def cancel_research(job_id: str, who: models.Integration = Depends(integration), db: Session = Depends(get_db)):
    """Stop a running job; the partial answer is kept with status "stopped" (status is "stopping" until then)."""
    view = svc.job_view(_call(svc.cancel_research, db, who, job_id))
    if view.status in ("queued", "running"):
        view.status = "stopping"
    return view


@api.get("/answers", response_model=list[schemas.ResearchSummary], summary="Search past answers")
def search_answers(
    q: str = "", limit: int = 20, who: models.Integration = Depends(integration), db: Session = Depends(get_db)
):
    """This integration's questions, newest first; `q` matches the question or the answer text."""
    return [svc.summary_view(t) for t in _call(svc.search_answers, db, who, q, limit)]


def mount(app: FastAPI) -> None:
    app.mount("/api/v1", api)

