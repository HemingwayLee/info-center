"""PDF to Markdown conversion. Runs locally with PyMuPDF4LLM; nothing is sent to Claude.

Used by the Papers tab (app/papers.py) and by the plain conversion endpoint below.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pymupdf4llm
from fastapi import APIRouter, File, HTTPException, UploadFile

MAX_PDF_BYTES = 50 * 1024 * 1024
IMAGE_DPI = 150
# Where image links in the Markdown point: a folder next to the Markdown file.
IMAGES_DIR = "images"
_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*#*\s*$", re.MULTILINE)

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


@dataclass
class Converted:
    pages: int
    markdown: str  # the whole document, for people
    paged_markdown: str  # the same with "<!-- page N -->" before each page, so Claude can cite pages
    title: str | None  # from the PDF's metadata or its first heading, if it has a usable one


def read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Not a PDF file")
    return data


def _title(doc: pymupdf.Document, first_page: str) -> str | None:
    meta = (doc.metadata or {}).get("title", "").strip()
    # Metadata titles are often junk left by the authoring tool ("untitled", "Microsoft Word - draft.docx").
    if len(meta) > 8 and not re.search(r"untitled|\.(docx?|tex|dvi|pdf)$|^microsoft word", meta, re.IGNORECASE):
        return meta[:300]
    match = _HEADING.search(first_page)
    if match:
        heading = re.sub(r"[*_`]+", "", match.group(1)).strip()
        if len(heading) > 8:
            return heading[:300]
    return None


def _relative_images(text: str, image_dir: Path) -> str:
    """Point image links at IMAGES_DIR/<file>, relative to the Markdown, instead of the absolute path written."""
    return re.sub(
        r"!\[([^\]]*)\]\(" + re.escape(str(image_dir)) + r"/([^)]+)\)",
        lambda m: f"![{m.group(1)}]({IMAGES_DIR}/{_image_name(m.group(2))})",
        text,
    )


def _image_name(name: str) -> str:
    # Opened from bytes, the document has no name, so the files are called "-0003-00.png" (page 3, image 0).
    return f"page{name}" if name.startswith("-") else name


def convert(data: bytes, image_dir: Path | None = None) -> Converted:
    """Convert a PDF's bytes; raises HTTPException with a reason people can act on. CPU-bound: run in a thread.

    With `image_dir`, the PDF's images are saved there as PNGs and linked from the Markdown as
    images/<file>, relative to it (so the Markdown belongs in image_dir's parent folder).
    """
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise HTTPException(400, f"Could not open PDF: {e}") from e
    with doc:
        if doc.needs_pass:
            raise HTTPException(400, "PDF is password-protected")
        try:
            options = {}
            if image_dir is not None:
                image_dir.mkdir(parents=True, exist_ok=True)
                options = {"write_images": True, "image_path": str(image_dir), "image_format": "png", "dpi": IMAGE_DPI}
            chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, **options)
        except Exception as e:
            raise HTTPException(422, f"Could not convert PDF: {e}") from e
        texts = [c["text"].strip() for c in chunks]
        if image_dir is not None:
            for path in image_dir.iterdir():
                if path.name != _image_name(path.name):
                    path.rename(path.with_name(_image_name(path.name)))
            texts = [_relative_images(t, image_dir) for t in texts]
        paged = "\n\n".join(
            f"<!-- page {c['metadata'].get('page_number', i + 1)} -->\n\n{text}"
            for i, (c, text) in enumerate(zip(chunks, texts))
        )
        return Converted(
            pages=doc.page_count,
            markdown="\n\n".join(t for t in texts if t),
            paged_markdown=paged,
            title=_title(doc, texts[0] if texts else ""),
        )


@router.post("/markdown")
def pdf_to_markdown(file: UploadFile = File(...)) -> dict:
    """Convert an uploaded PDF to Markdown. A sync endpoint, so FastAPI runs the CPU-bound work in a thread."""
    converted = convert(read_upload(file))
    return {"filename": file.filename, "pages": converted.pages, "markdown": converted.markdown}
