"""Bridge between the chat API and Claude Code via the Claude Agent SDK."""

import os
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from app.config import settings

MODELS = [
    {"id": "claude-opus-5-5", "name": "Claude Opus 5.5"},
    {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
    {"id": "claude-haiku-5-5", "name": "Claude Haiku 5.5"},
    {"id": "claude-fable-5-1", "name": "Claude Fable 5.1"},
]

# Appended to Claude Code's system prompt when the user turns on "Ref" for a message. The chat UI turns
# `[text](cite:1,2)` into text colored by the cited source's credibility level (see the Source tab), followed
# by a [1, 2] marker, and `[text](conf:85)` (Claude's own statements) into normal text with an 85% badge.
RESEARCH_PROMPT = """
# Research mode

The user turned on "Ref" for this message. Answer like a researcher writing a paper: every statement is either
backed by a cited source, or marked as your own with a confidence score, so the reader can see where each part
of the answer comes from and how much to trust it.

## How to work
- Facts you are not very sure of, or that may have changed (recent events, current figures, prices, people in
  office, statistics, anything after your training data), must be checked: use WebSearch to find sources and
  WebFetch to open the pages you rely on, so each citation reflects what the source actually says.
- Facts you are very sure of (well-established, stable knowledge) you may state from your own knowledge
  without searching, marked with your confidence (below). When in doubt, search.
- Prefer primary and reliable sources. The user rates these most credible: {preferred}.
- Avoid relying on low-credibility sources such as {avoid}. If one is the only source for a claim, cite it
  and say plainly that the claim is weakly sourced.
- If a source and your own knowledge disagree, say so instead of silently picking one.

## Marking every statement
Each sentence or clause that states something is exactly one of:

1. **From a source**: wrap it in a Markdown link whose target is `cite:` plus the reference numbers:
   `[Global sea level rose about 5.9 mm in 2024](cite:1)` or `[...](cite:2,3)`. Wrap the claim itself, not a
   phrase naming the source: `[Sea level rose 5.9 mm in 2024](cite:1), according to NASA`, not
   `according to [NASA](cite:1)`. Never attach a citation to a claim the source doesn't make.
2. **From you** (your knowledge, reasoning, inference, estimate, guess or opinion): wrap it in a link whose
   target is `conf:` plus your confidence from 0 to 100 that it is correct:
   `[Water boils at 100 °C at sea level](conf:99)`, `[The decline will likely continue through 2030](conf:70)`.
   Be calibrated and honest:
   - 95-100: certain, well-established fact
   - 80-94: confident, but unverified or possibly outdated
   - 50-79: reasoned inference or educated estimate
   - below 50: speculation or a guess (also say so in words: "My guess is…")

Every sentence that makes a claim needs one of these two markers, including caveats and summaries of what
"other sources" say (cite them if you opened them, otherwise mark the claim as yours with a confidence).
Leave only connective text unmarked: transitions, headings, and questions to the user ("Here's what I found:").
Wrap a clause or sentence at most, never across paragraphs, list items or table cells (in tables, wrap the
cell text), and don't nest links, inline code or other markers inside a wrapped span.

If anything is cited, end the answer with a references section, numbered in order of first citation:

## References
1. [Page or paper title](https://exact.url/you/used) - Publisher
2. [Another title](https://another.url/page) - Publisher

Rules:
- Cite only URLs you actually opened or that were given to you in this conversation. Never invent or guess a URL.
- Number references per answer starting at 1, and reuse a number when you cite the same source again.
"""


def research_prompt(sources_by_level: dict[int, list[str]]) -> str:
    """The research-mode instructions, naming the user's own credible and low-credibility sources."""
    def names(levels: tuple[int, ...], fallback: str) -> str:
        found = [n for lv in levels for n in sources_by_level.get(lv, [])]
        return ", ".join(found) if found else fallback

    return RESEARCH_PROMPT.format(
        preferred=names((1, 2), "government, academic and peer-reviewed sources and established newsrooms"),
        avoid=names((4,), "anonymous forums, content farms and viral social media posts"),
    )


def ensure_credentials() -> None:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
        raise RuntimeError(
            "No Claude credentials. Set CLAUDE_CODE_OAUTH_TOKEN (Pro/Max plan, from `claude setup-token`) "
            "or ANTHROPIC_API_KEY in .env, then run `docker compose -f docker-compose.dev.yml up -d backend`."
        )


def _tool_result_content(content: Any) -> str:
    """Tool output as text for the UI, truncated: Claude still sees it in full, the browser doesn't need to."""
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    else:
        text = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    limit = settings.tool_result_display_chars
    if len(text) > limit:
        text = f"{text[:limit]}\n\n… [{len(text) - limit:,} more characters not shown]"
    return text


async def run_turn(
    prompt: str,
    model: str,
    resume: str | None,
    research: str | None = None,
    allowed_tools: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run one chat turn through Claude Code and yield UI events.

    `research` is extra system-prompt text for research mode (see research_prompt), or None to answer normally.
    `allowed_tools` overrides settings.claude_allowed_tools and also limits which tools exist at all, so Claude
    can't use anything else (integrations get a research-only set). allowed_tools alone isn't a hard limit:
    Claude Code still runs commands it considers harmless, like `echo`, without asking.

    Event shapes:
      {"type": "session", "session_id"}
      {"type": "text", "text"}                       incremental text delta
      {"type": "tool_use", "id", "name", "input"}
      {"type": "tool_result", "tool_use_id", "content", "is_error"}
      {"type": "result", "session_id", "cost_usd", "is_error", "subtype"}
    """
    ensure_credentials()
    # On a subscription, total_cost_usd is an API-price estimate, not what you're billed.
    uses_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    options = ClaudeAgentOptions(
        model=model,
        cwd=settings.claude_workspace,
        resume=resume,
        # snapshot=False rebuilds the prompt every turn, so research mode can differ from message to message.
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "snapshot": False,
            **({"append": research} if research else {}),
        },
        allowed_tools=settings.claude_allowed_tools if allowed_tools is None else allowed_tools,
        # A restricted run only gets the listed tools; Claude never sees the rest.
        **({"tools": allowed_tools} if allowed_tools is not None else {}),
        # No interactive approval in the web UI: anything not in allowed_tools is denied.
        permission_mode="dontAsk",
        include_partial_messages=True,
        # Large tool results (web pages, files, subagent reports) can exceed the SDK's 1 MB default.
        max_buffer_size=settings.claude_max_buffer_bytes,
    )

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            yield {"type": "session", "session_id": message.data.get("session_id")}

        elif isinstance(message, StreamEvent) and message.parent_tool_use_id is None:
            event = message.event
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield {"type": "text", "text": delta.get("text", "")}
            elif event.get("type") == "message_start":
                # Separate text from consecutive assistant messages within one turn.
                yield {"type": "message_start"}

        elif isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
            # Text already arrived via stream deltas; only surface tool calls here.
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    yield {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}

        elif (
            isinstance(message, UserMessage)
            and message.parent_tool_use_id is None  # skip subagents' internal tool results
            and isinstance(message.content, list)
        ):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    yield {
                        "type": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": _tool_result_content(block.content),
                        "is_error": bool(block.is_error),
                    }

        elif isinstance(message, ResultMessage):
            yield {
                "type": "result",
                "session_id": message.session_id,
                "cost_usd": message.total_cost_usd if uses_api_key else None,
                "is_error": message.is_error,
                "subtype": message.subtype,
                "result": message.result if message.is_error else None,
            }
