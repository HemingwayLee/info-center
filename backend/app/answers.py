"""Answer formatting: parse references, resolve source credibility, and build the portable export.

Stored answers keep the chat UI's span markers, which record exactly which words a citation or confidence
covers:
    [claim from a source](cite:1,2)      [Claude's own claim](conf:85)
The export also has `content_markdown` in a plain form any LLM understands:
    claim from a source [1, 2]           Claude's own claim (confidence: 85%)
"""

import json
import re
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 1

CONVENTIONS = (
    "[n] cites reference n in `references`. (confidence: N%) marks a claim the answering model made from its "
    "own knowledge or reasoning, without a source, with its confidence that it is correct. Reference `level` "
    "is the user's credibility rating for that source: 1 (most credible) to 4 (least); null means unrated."
)

# ---- References section -------------------------------------------------------------------------------

_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?\**\s*(references|sources)\s*:?\s*\**\s*$", re.IGNORECASE)
_ITEM = re.compile(r"^\s*(?:[-*]\s*)?\[?(\d+)\]?[.):]?\s+(.+)$")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://(?:[^\s()]|\([^\s()]*\))+)\)")
_BARE_URL = re.compile(r"https?://[^\s<>()\]]+(?:\([^\s<>()]*\)[^\s<>()\]]*)*")
_EDGE_PUNCT = re.compile(r"^[\s\-–—:,.·|]+|[\s\-–—:,.·|]+$")


def _parse_reference(line: str) -> dict[str, Any] | None:
    m = _ITEM.match(line)
    if not m:
        return None
    rest = m.group(2)
    link = _LINK.search(rest)
    if link:
        title, url = link.group(1), link.group(2)
        publisher = _EDGE_PUNCT.sub("", rest[link.end():])
    else:
        bare = _BARE_URL.search(rest)
        if not bare:
            return None
        url = bare.group(0).rstrip(".,;:")
        title = _EDGE_PUNCT.sub("", rest.replace(bare.group(0), "").replace("<", "").replace(">", ""))
        publisher = ""
    return {"n": int(m.group(1)), "url": url, "title": title or url, "publisher": publisher or None}


def split_references(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Split an answer into (body, references) at its last "References" heading.

    Mirrors splitReferences in frontend/src/citations.js, which handles the live stream before it's saved.
    """
    lines = text.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if not _HEADING.match(lines[i]):
            continue
        refs = [r for r in (_parse_reference(line) for line in lines[i + 1:]) if r]
        if not refs:
            break
        by_number = {r["n"]: r for r in refs}  # last definition of a number wins
        return "\n".join(lines[:i]).rstrip(), [by_number[n] for n in sorted(by_number)]
    return text, []


# ---- Plain markers -------------------------------------------------------------------------------------

# [text](cite:1,2) or [text](conf:85); the text may contain one level of nested brackets.
_MARKER = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\((cite|conf):([^)\n]*)\)")


def _plain_marker(m: re.Match) -> str:
    text, kind, value = m.group(1), m.group(2), m.group(3)
    if kind == "cite":
        numbers = [n for n in re.split(r"[\s,]+", value) if n.isdigit()]
        return f"{text} [{', '.join(numbers)}]" if numbers else text
    try:
        pct = max(0, min(100, round(float(value.strip().rstrip('%')))))
    except ValueError:
        return text
    return f"{text} (confidence: {pct}%)"


def plain_markdown(annotated: str) -> str:
    """Replace the UI's span markers with paper-style [1] citations and (confidence: N%) notes."""
    return _MARKER.sub(_plain_marker, annotated)


# ---- Source credibility (mirrors matchSource in frontend/src/sources.js) --------------------------------


def hostname(url: str) -> str | None:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    return host.removeprefix("www.") or None


def _patterns(name: str) -> list[tuple[str, str]]:
    tokens = [t for t in re.split(r"[\s(),（）]+", name.lower()) if t]
    has_domain = any("." in t for t in tokens)
    patterns = []
    for t in tokens:
        if t.startswith("."):
            patterns.append(("suffix", t))
        elif "." in t:
            patterns.append(("domain", t))
        elif len(tokens) == 1 or has_domain:
            patterns.append(("label", t))
    return patterns


def _score(host: str, kind: str, value: str) -> int:
    if kind == "domain":
        return 100 + len(value) if host == value or host.endswith(f".{value}") else 0
    if kind == "label":
        return 50 if value in host.split(".") else 0
    if kind == "suffix":
        return len(value) if host.endswith(value) or f"{value}." in host else 0
    return 0


def source_level(url: str, sources: list[tuple[str, int]]) -> int | None:
    """Credibility level of the most specific matching source ("npr.org" beats ".org"), or None if unrated."""
    host = hostname(url)
    if not host:
        return None
    best_level, best_score = None, 0
    for name, level in sources:
        for kind, value in _patterns(name):
            score = _score(host, kind, value)
            if score > best_score:
                best_level, best_score = level, score
    return best_level


def with_levels(references: list[dict[str, Any]], sources: list[tuple[str, int]]) -> list[dict[str, Any]]:
    return [{**r, "level": source_level(r["url"], sources)} for r in references]


# ---- Export --------------------------------------------------------------------------------------------


def consulted(activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The web searches and pages the model used while answering."""
    found = []
    for block in activity:
        if block.get("type") != "tool_use":
            continue
        tool, args = block.get("name"), block.get("input") or {}
        if tool == "WebSearch" and args.get("query"):
            found.append({"tool": tool, "query": args["query"]})
        elif tool == "WebFetch" and args.get("url"):
            found.append({"tool": tool, "url": args["url"]})
    return found


def export_turn(turn, sources: list[tuple[str, int]]) -> dict[str, Any]:
    """One question and answer in the portable format. Levels reflect the Source list at export time."""
    return {
        "schema_version": SCHEMA_VERSION,
        "uuid": str(turn.uuid),
        "question": turn.question,
        "created_at": turn.created_at.isoformat().replace("+00:00", "Z"),
        "model": turn.model,
        "mode": turn.mode,
        "content_markdown": plain_markdown(turn.content),
        "references": with_levels(turn.references or [], sources),
        "conventions": CONVENTIONS,
        "status": turn.status,
        "error": turn.error,
        "consulted": consulted(turn.activity or []),
        # Same answer with the UI's span markers, which record exactly which words each citation covers.
        "content_annotated": turn.content,
        "id": turn.id,
        "conversation": {
            "uuid": str(turn.conversation.uuid),
            "id": turn.conversation.id,
            "title": turn.conversation.title,
        },
    }


def _yaml_str(value: Any) -> str:
    # A JSON string is a valid double-quoted YAML scalar.
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else json.dumps(value)


def export_markdown(data: dict[str, Any]) -> str:
    """The export as one Markdown document (front matter + question + answer + references) to paste into an LLM."""
    front = ["---"]
    for key in ("schema_version", "uuid", "question", "created_at", "model", "mode", "status", "conventions"):
        front.append(f"{key}: {_yaml_str(data[key])}")
    front.append("---")

    parts = ["\n".join(front), "# Question", data["question"], "# Answer", data["content_markdown"] or "(no answer)"]
    if data["error"]:
        parts.append(f"> Error: {data['error']}")
    if data["references"]:
        lines = []
        for r in data["references"]:
            publisher = f", {r['publisher']}" if r.get("publisher") else ""
            level = f"Lv{r['level']}" if r.get("level") else "unrated"
            lines.append(f"[{r['n']}] {r['title']}{publisher}. {r['url']} ({level})")
        parts.append("## References\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"
