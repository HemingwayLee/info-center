"""Source credibility levels and the websites/platforms assigned to each."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import SessionLocal, get_db

LEVELS = [
    {
        "level": 1,
        "name": "High credibility",
        "description": "Government, academic and non-profit sites, and peer-reviewed papers (.gov, .edu, .org, Nature, Science, …).",
    },
    {
        "level": 2,
        "name": "Good credibility",
        "description": "Mainstream media with a strong record for accuracy and corrections (BBC, The New York Times, …).",
    },
    {
        "level": 3,
        "name": "Moderate credibility",
        "description": "Named experts, specialized columns, and mainstream media with moderate credibility.",
    },
    {
        "level": 4,
        "name": "Low credibility",
        "description": "Anonymous forums, content farms, messaging apps and viral social media posts.",
    },
]
LEVEL_IDS = {lv["level"] for lv in LEVELS}

# Inserted once, when the table is empty.
DEFAULT_SOURCES = {
    1: [
        ".gov", ".edu", ".org", "nature.com", "science.org", "thelancet.com", "nejm.org",
        "cell.com", "pubmed.ncbi.nlm.nih.gov", "who.int",
    ],
    2: [
        "bbc.com", "nytimes.com", "reuters.com", "apnews.com", "theguardian.com", "washingtonpost.com",
        "wsj.com", "economist.com", "ft.com", "bloomberg.com", "npr.org",
    ],
    3: [
        "cnn.com", "foxnews.com", "forbes.com", "businessinsider.com", "huffpost.com", "nypost.com",
        "substack.com", "medium.com",
    ],
    4: [
        "LINE", "WhatsApp", "reddit.com", "quora.com", "PTT (ptt.cc)", "threads.net", "x.com (Twitter)",
        "facebook.com", "tiktok.com", "Content farms", "Viral social media posts",
    ],
}

router = APIRouter(prefix="/api/sources", tags=["sources"])


def seed_sources() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(models.Source)):
            return
        db.add_all(
            models.Source(name=name, level=level)
            for level, names in DEFAULT_SOURCES.items()
            for name in names
        )
        db.commit()


def _check_level(level: int) -> None:
    if level not in LEVEL_IDS:
        raise HTTPException(status_code=422, detail=f"Level must be one of {sorted(LEVEL_IDS)}")


def _ensure_unique(db: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(models.Source).where(func.lower(models.Source.name) == name.lower())
    existing = db.scalars(stmt).first()
    if existing is not None and existing.id != exclude_id:
        raise HTTPException(status_code=409, detail=f'"{existing.name}" is already in Lv{existing.level}')


def _get_source(db: Session, source_id: int) -> models.Source:
    source = db.get(models.Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/levels")
def list_levels():
    return LEVELS


@router.get("", response_model=list[schemas.SourceRead])
def list_sources(db: Session = Depends(get_db)):
    return db.scalars(select(models.Source).order_by(models.Source.level, models.Source.id)).all()


@router.post("", response_model=schemas.SourceRead, status_code=201)
def create_source(payload: schemas.SourceCreate, db: Session = Depends(get_db)):
    _check_level(payload.level)
    _ensure_unique(db, payload.name)
    source = models.Source(name=payload.name, level=payload.level)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.patch("/{source_id}", response_model=schemas.SourceRead)
def update_source(source_id: int, payload: schemas.SourceUpdate, db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    data = payload.model_dump(exclude_unset=True)
    if "level" in data:
        _check_level(data["level"])
    if "name" in data:
        _ensure_unique(db, data["name"], exclude_id=source.id)
    for field, value in data.items():
        setattr(source, field, value)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: int, db: Session = Depends(get_db)):
    db.delete(_get_source(db, source_id))
    db.commit()
