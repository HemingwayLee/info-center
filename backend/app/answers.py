"""Answer formatting: parse references and annotations, resolve source credibility, build the portable export.

Claude marks which words a citation or confidence covers with span markers (see RESEARCH_PROMPT in claude.py):
    [claim from a source](cite:1,2)      [Claude's own claim](conf:85)
Saved answers don't keep them. `content` is plain Markdown, and each marker becomes an entry in `annotations`:
    {"start": 0, "end": 19, "cite": [1, 2]}      {"start": 21, "end": 39, "confidence": 85}
with start/end as Unicode code point offsets into `content` (end exclusive). The chat UI puts the markers back
to render them (withMarkers in frontend/src/citations.js); the Markdown export writes them in a plain form any
LLM understands:
    claim from a source [1, 2]           Claude's own claim (confidence: 85%)
"""

import json
import re
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 2

CONVENTIONS = (
    "`content` is the answer as Markdown. Each `annotations` entry covers content[start:end], counted in Unicode "
    "code points (end exclusive): `cite` lists the numbers of the `references` that text comes from; "
    "`confidence` (0-100) marks a claim the answering model made from its own knowledge or reasoning, without a "
    "source, with its confidence that it is correct. In the Markdown export, [n] cites reference n and "
    "(confidence: N%) follows such a claim. Reference `level` is the user's credibility rating for that source: "
    "1 (most credible) to 4 (least); null means unrated."
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


# ---- Annotations --------------------------------------------------------------------------------------

# [text](cite:1,2) or [text](conf:85); the text may contain one level of nested brackets.
_MARKER = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\((cite|conf):([^)\n]*)\)")


def _marker_value(kind: str, value: str) -> dict[str, Any] | None:
    """{"cite": [1, 2]} or {"confidence": 85} from a marker's value, or None if it has no usable value."""
    if kind == "cite":
        numbers = [int(n) for n in re.split(r"[\s,]+", value) if n.isdigit() and int(n) > 0]
        return {"cite": numbers} if numbers else None
    try:
        return {"confidence": max(0, min(100, round(float(value.strip().rstrip("%")))))}
    except ValueError:
        return None


def extract_annotations(annotated: str) -> tuple[str, list[dict[str, Any]]]:
    """Strip the span markers from an answer: (plain Markdown, [{"start", "end", "cite" | "confidence"}]).

    Offsets are code point indexes into the returned text. A marker with no usable value keeps its text only.
    """
    parts: list[str] = []
    annotations: list[dict[str, Any]] = []
    length = 0  # code points written so far
    last = 0
    for m in _MARKER.finditer(annotated):
        before, inner = annotated[last:m.start()], m.group(1)
        parts += [before, inner]
        length += len(before)
        value = _marker_value(m.group(2), m.group(3))
        if value is not None and inner:
            annotations.append({"start": length, "end": length + len(inner), **value})
        length += len(inner)
        last = m.end()
    parts.append(annotated[last:])
    return "".join(parts), annotations


def _apply_annotations(content: str, annotations: list[dict[str, Any]], render) -> str:
    """`content` with each annotated span replaced by render(text, annotation); bad or overlapping spans skipped."""
    out, pos = [], 0
    for a in sorted(annotations, key=lambda a: a["start"]):
        start, end = a.get("start"), a.get("end")
        if not (isinstance(start, int) and isinstance(end, int) and pos <= start < end <= len(content)):
            continue
        out += [content[pos:start], render(content[start:end], a)]
        pos = end
    out.append(content[pos:])
    return "".join(out)


def _plain(text: str, a: dict[str, Any]) -> str:
    if a.get("cite"):
        return f"{text} [{', '.join(str(n) for n in a['cite'])}]"
    if a.get("confidence") is not None:
        return f"{text} (confidence: {a['confidence']}%)"
    return text


def _marker(text: str, a: dict[str, Any]) -> str:
    if a.get("cite"):
        return f"[{text}](cite:{','.join(str(n) for n in a['cite'])})"
    if a.get("confidence") is not None:
        return f"[{text}](conf:{a['confidence']})"
    return text


def plain_markdown(content: str, annotations: list[dict[str, Any]]) -> str:
    """The answer with paper-style [1] citations and (confidence: N%) notes after its annotated spans."""
    return _apply_annotations(content, annotations, _plain)


def with_markers(content: str, annotations: list[dict[str, Any]]) -> str:
    """The answer with Claude's span markers put back (mirrors withMarkers in frontend/src/citations.js)."""
    return _apply_annotations(content, annotations, _marker)


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


def export_turn(
    turn, annotated: str, references: list[dict[str, Any]], sources: list[tuple[str, int]]
) -> dict[str, Any]:
    """One question and answer in the portable format, stored in turns.metadata when the answer is saved.

    `annotated` is the answer with Claude's span markers and without its References section, which was parsed
    into `references` (split_references). Levels reflect the Source list when the answer was saved.
    """
    content, annotations = extract_annotations(annotated)
    return {
        "schema_version": SCHEMA_VERSION,
        "uuid": str(turn.uuid),
        "question": turn.question,
        "created_at": turn.created_at.isoformat().replace("+00:00", "Z"),
        "model": turn.model,
        "mode": turn.mode,
        "content": content,
        "annotations": annotations,
        "references": with_levels(references, sources),
        "conventions": CONVENTIONS,
        "status": turn.status,
        "error": turn.error,
        "consulted": consulted(turn.activity or []),
        "id": turn.id,
        "conversation": {
            "uuid": str(turn.conversation.uuid),
            "id": turn.conversation.id,
            "title": turn.conversation.title,
        },
    }


def upgrade_export(data: dict[str, Any]) -> dict[str, Any]:
    """A stored schema_version 1 export as version 2, keeping its references and levels as saved."""
    if data.get("schema_version", 1) >= 2:
        return data
    content, annotations = extract_annotations(data.get("content_annotated") or "")
    upgraded = {}
    for key, value in data.items():
        if key == "content_markdown":
            upgraded["content"], upgraded["annotations"] = content, annotations
        elif key != "content_annotated":
            upgraded[key] = value
    upgraded.setdefault("content", content)
    upgraded.setdefault("annotations", annotations)
    upgraded["schema_version"], upgraded["conventions"] = 2, CONVENTIONS
    return upgraded


def _yaml_str(value: Any) -> str:
    # A JSON string is a valid double-quoted YAML scalar.
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else json.dumps(value)


def export_markdown(data: dict[str, Any]) -> str:
    """The export as one Markdown document (front matter + question + answer + references) to paste into an LLM."""
    front = ["---"]
    for key in ("schema_version", "uuid", "question", "created_at", "model", "mode", "status", "conventions"):
        front.append(f"{key}: {_yaml_str(data[key])}")
    front.append("---")

    answer = plain_markdown(data["content"], data["annotations"])
    parts = ["\n".join(front), "# Question", data["question"], "# Answer", answer or "(no answer)"]
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
