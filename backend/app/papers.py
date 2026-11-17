"""Papers tab: a library of PDFs, each with a chat for questions about it.

Uploading converts the PDF to Markdown (app/pdf.py) and stores both in the Claude workspace, where Claude can read
them while answering:

    <workspace>/papers/<uuid>/paper.pdf    the original
    <workspace>/papers/<uuid>/paper.md     the Markdown, with "<!-- page N -->" before each page
    <workspace>/papers/<uuid>/images/      the PDF's images, linked from the Markdown as images/<file>

Each paper has one conversation (conversations.paper_id), sent through the normal chat endpoints
(POST /api/conversations/{id}/messages and friends); main.py asks chat_context() what to add for a paper chat.
"""

import logging
import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs, models, schemas
from app.config import settings
from app.db import SessionLocal, get_db
from app.pdf import IMAGES_DIR, convert, read_upload

logger = logging.getLogger(__name__)
_IMAGE_NAME = re.compile(r"^[\w.-]+\.(png|jpe?g)$")

router = APIRouter(prefix="/api/papers", tags=["papers"])

PAPER_PROMPT = """
# The paper

The user is reading a paper and asks you about it: "{title}" ({pages} pages, file {filename}).
- {md_path}: the paper as Markdown, converted from the PDF, with "<!-- page N -->" before each page's text.
- {pdf_path}: the original PDF. The Markdown can garble equations, tables and figures; when they matter, Read
  the PDF with the `pages` parameter (e.g. pages "4") to see the actual page.
- {images_path}: the paper's figures and other images. The Markdown links them where they appear, as
  `![](images/<file>)` relative to the paper's folder; Read an image to look at it when a question is about it.
{access}

How to answer:
- The user finds the paper hard to read. Explain in plain language first, then the details; define jargon and
  symbols the first time you use them; use small concrete examples or analogies when they help.
- Ground answers in the paper. Cite the page of each statement taken from it as a link: [p. 4](page:4), or
  [pp. 4-5](page:4) for a range (link to the first page). The user clicks these to open the PDF at that page.
- Quote the paper's exact wording when precision matters (definitions, claims, numbers).
- Say clearly when the paper doesn't say something. If you add your own knowledge or something from the web,
  say so, and for the web give the link.
"""

ACCESS_INLINE = "Its full text is in the first message of this conversation, so you normally don't need to read files."
ACCESS_FILE = (
    "It is too long to include here: Read paper.md in parts (offset and limit) or Grep it for what the question "
    "needs before answering."
)

FIRST_MESSAGE = """Here is the paper's full text (from paper.md), for this conversation:

<paper>
{text}
</paper>

My question: {question}"""


def _dir(paper: models.Paper) -> Path:
    return Path(settings.claude_workspace) / "papers" / str(paper.uuid)


def _get(db: Session, paper_id: int) -> models.Paper:
    paper = db.get(models.Paper, paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found")
    return paper


def _conversation(paper: models.Paper) -> models.Conversation:
    return paper.conversations[0]


def _view(paper: models.Paper) -> dict:
    convo = _conversation(paper)
    return {
        **schemas.PaperRead.model_validate(paper).model_dump(),
        "conversation_id": convo.id,
        "questions": len(convo.turns),
    }


def chat_context(paper: models.Paper, conversation: models.Conversation, question: str) -> tuple[str, str]:
    """(system prompt addition, what Claude gets as the message) for a question in a paper's chat.

    The paper's text goes in the message, not the system prompt: the SDK passes the system prompt as a command
    line argument, which is size-limited. It's sent with the first question of a session; later questions resume
    that session, which already has it.
    """
    folder = _dir(paper)
    paged = (folder / "paper.md").read_text() if (folder / "paper.md").exists() else paper.markdown
    inline = len(paged) <= settings.paper_inline_chars
    system = PAPER_PROMPT.format(
        title=paper.title,
        pages=paper.pages,
        filename=paper.filename,
        md_path=folder / "paper.md",
        pdf_path=folder / "paper.pdf",
        images_path=folder / IMAGES_DIR,
        access=ACCESS_INLINE if inline else ACCESS_FILE,
    )
    if inline and conversation.claude_session_id is None:
        return system, FIRST_MESSAGE.format(text=paged, question=question)
    return system, question


@router.get("", response_model=list[schemas.PaperSummary])
def list_papers(db: Session = Depends(get_db)):
    """Newest first."""
    return [_view(p) for p in db.scalars(select(models.Paper).order_by(models.Paper.id.desc()))]


@router.post("", response_model=schemas.PaperSummary, status_code=201)
def upload_paper(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Add a PDF (up to 50 MB): convert it and create its chat. Sync, so the conversion runs in a thread."""
    data = read_upload(file)
    paper_uuid = uuid4()  # names the paper's folder, which the conversion writes images into
    folder = Path(settings.claude_workspace) / "papers" / str(paper_uuid)
    try:
        converted = convert(data, folder / IMAGES_DIR)
        filename = (file.filename or "paper.pdf")[:300]
        title = converted.title or (filename[:-4] if filename.lower().endswith(".pdf") else filename) or "Untitled paper"
        paper = models.Paper(
            uuid=paper_uuid,
            title=title[:300],
            filename=filename,
            pages=converted.pages,
            size_bytes=len(data),
            markdown=converted.markdown,
        )
        paper.conversations.append(models.Conversation(title=title[:200], model=settings.claude_default_model))
        db.add(paper)
        (folder / "paper.pdf").write_bytes(data)
        (folder / "paper.md").write_text(converted.paged_markdown)
        db.commit()
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    db.refresh(paper)
    return _view(paper)


@router.get("/{paper_id}", response_model=schemas.PaperDetail)
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = _get(db, paper_id)
    return {**_view(paper), "markdown": paper.markdown}


@router.get("/{paper_id}/pdf")
def get_paper_pdf(paper_id: int, db: Session = Depends(get_db)):
    """The original PDF, shown inline (the browser's PDF viewer)."""
    paper = _get(db, paper_id)
    path = _dir(paper) / "paper.pdf"
    if not path.exists():
        raise HTTPException(404, "The PDF file is missing from the workspace")
    return FileResponse(path, media_type="application/pdf", filename=paper.filename, content_disposition_type="inline")


@router.get("/{paper_id}/images/{name}")
def get_paper_image(paper_id: int, name: str, db: Session = Depends(get_db)):
    """One of the paper's images, as linked from its Markdown (images/<name>)."""
    if not _IMAGE_NAME.match(name):
        raise HTTPException(404, "Image not found")
    path = _dir(_get(db, paper_id)) / IMAGES_DIR / name
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    # Never changes for a given paper and name, so browsers may keep it.
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.patch("/{paper_id}", response_model=schemas.PaperSummary)
def rename_paper(paper_id: int, payload: schemas.PaperUpdate, db: Session = Depends(get_db)):
    paper = _get(db, paper_id)
    paper.title = payload.title
    _conversation(paper).title = payload.title[:200]
    db.commit()
    db.refresh(paper)
    return _view(paper)


@router.delete("/{paper_id}", status_code=204)
async def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    """Delete a paper, its files and its chat (stopping an answer being written)."""
    paper = _get(db, paper_id)
    for turn in _conversation(paper).turns:
        if turn.status == "running":
            jobs.cancel(turn.id)
    folder = _dir(paper)
    db.delete(paper)
    db.commit()
    shutil.rmtree(folder, ignore_errors=True)


@router.post("/{paper_id}/clear-chat", response_model=schemas.PaperSummary)
def clear_chat(paper_id: int, db: Session = Depends(get_db)):
    """Start the paper's chat over: delete its questions and answers and Claude's session."""
    paper = _get(db, paper_id)
    convo = _conversation(paper)
    if any(t.status == "running" for t in convo.turns):
        raise HTTPException(409, "Wait for the answer being written to finish, or stop it")
    convo.turns.clear()
    convo.claude_session_id = None
    db.commit()
    db.refresh(paper)
    return _view(paper)


def backfill_images() -> None:
    """Re-convert papers added before images were extracted (no images folder yet), so their Markdown shows them.

    Runs once per paper, in the background at startup. Their chats keep the old text until cleared.
    """
    with SessionLocal() as db:
        for paper in db.scalars(select(models.Paper).order_by(models.Paper.id)):
            folder = _dir(paper)
            if (folder / IMAGES_DIR).exists() or not (folder / "paper.pdf").exists():
                continue
            try:
                converted = convert((folder / "paper.pdf").read_bytes(), folder / IMAGES_DIR)
            except Exception:
                logger.exception("Couldn't extract images for paper %s", paper.id)
                (folder / IMAGES_DIR).mkdir(exist_ok=True)  # don't retry on every start
                continue
            (folder / "paper.md").write_text(converted.paged_markdown)
            paper.markdown = converted.markdown
            db.commit()
            logger.info("Extracted images for paper %s (%s)", paper.id, paper.title)
