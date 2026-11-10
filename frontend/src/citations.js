// Claude marks sourced text as [text](cite:1,2) and ends with a "References" section (see CITATION_PROMPT
// in backend/app/claude.py). The backend parses saved answers the same way (split_references in
// backend/app/answers.py); this handles the answer while it's still streaming.

const HEADING = /^\s*(?:#{1,6}\s*)?\**\s*(references|sources)\s*:?\s*\**\s*$/i;
const ITEM = /^\s*(?:[-*]\s*)?\[?(\d+)\]?[.):]?\s+(.+)$/;
const URL_RE = /https?:\/\/[^\s<>()\]]+(?:\([^\s<>()]*\)[^\s<>()\]]*)*/;

function parseItem(line) {
  const m = line.match(ITEM);
  if (!m) return null;
  const rest = m[2];
  // [title](url), allowing balanced parentheses inside the URL (Wikipedia-style links).
  const link = rest.match(/\[([^\]]+)\]\((https?:\/\/(?:[^\s()]|\([^\s()]*\))+)\)/);
  const url = link ? link[2] : rest.match(URL_RE)?.[0]?.replace(/[.,;:]+$/, "");
  if (!url) return null;
  const trim = (t) => t.replace(/^[\s\-–—:,.·|]+|[\s\-–—:,.·|]+$/g, "");
  const title = link ? link[1] : trim(rest.replace(url, "").replace(/[<>]/g, ""));
  const publisher = link ? trim(rest.slice(link.index + link[0].length)) : "";
  return { n: Number(m[1]), url, title: title || url, publisher: publisher || null };
}

/**
 * Split a text block into its body and the numbered references after its last "References" heading.
 * Returns { body, refs } where refs is [{ n, url, title }]; body is unchanged if there's no such section.
 */
export function splitReferences(text) {
  const lines = text.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!HEADING.test(lines[i])) continue;
    const refs = lines.slice(i + 1).map(parseItem).filter(Boolean);
    if (refs.length === 0) return { body: text, refs: [] };
    return { body: lines.slice(0, i).join("\n").trimEnd(), refs };
  }
  return { body: text, refs: [] };
}

/** "cite:1,2" → [1, 2] */
export const citeNumbers = (href) =>
  href
    .slice("cite:".length)
    .split(/[\s,]+/)
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0);
