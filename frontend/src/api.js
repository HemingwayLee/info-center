async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    // Surface FastAPI's {"detail": ...} message when there is one.
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : body?.detail?.[0]?.msg;
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  models: () => request("/models"),
  listConversations: () => request("/conversations"),
  getConversation: (id) => request(`/conversations/${id}`),
  createConversation: (model) =>
    request("/conversations", { method: "POST", body: JSON.stringify({ model }) }),
  updateConversation: (id, patch) =>
    request(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteConversation: (id) => request(`/conversations/${id}`, { method: "DELETE" }),
  promptHistory: () => request("/prompts/history"),

  sourceLevels: () => request("/sources/levels"),
  listSources: () => request("/sources"),
  createSource: (name, level) =>
    request("/sources", { method: "POST", body: JSON.stringify({ name, level }) }),
  updateSource: (id, patch) => request(`/sources/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteSource: (id) => request(`/sources/${id}`, { method: "DELETE" }),
};

/**
 * Send a chat message and stream Claude Code's reply as server-sent events.
 * Calls onEvent for each event; resolves when the stream ends.
 */
export async function streamMessage(conversationId, content, { research = false, onEvent, signal }) {
  const res = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, research }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`${res.status} ${res.statusText}`);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const data = chunk
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (data) onEvent(JSON.parse(data));
    }
  }
}

/** A turn being answered, before the server has saved it (no id yet). */
export const newTurn = (question, { research, model }) => ({
  id: null,
  question,
  mode: research ? "research" : "normal",
  model,
  content: "",
  references: [],
  activity: [],
  status: "running",
  error: null,
  cost_usd: null,
  newMessage: false,
});

const joinErrors = (a, b) => (a ? `${a}\n${b}` : b);

/** Fold a streamed event into the turn being answered (mirrors _Answer in backend/app/main.py). */
export function applyEvent(turn, event) {
  switch (event.type) {
    case "text": {
      let content = turn.content;
      // Text from consecutive assistant messages (e.g. before and after a tool call) is new paragraphs.
      if (turn.newMessage && content && !content.endsWith("\n\n")) content = `${content.replace(/\n+$/, "")}\n\n`;
      return { ...turn, content: content + event.text, newMessage: false };
    }
    case "message_start":
      return { ...turn, newMessage: true };
    case "tool_use":
    case "tool_result":
      return { ...turn, activity: [...turn.activity, event] };
    case "result":
      return event.is_error
        ? { ...turn, cost_usd: event.cost_usd, status: "error", error: joinErrors(turn.error, event.result || event.subtype) }
        : { ...turn, cost_usd: event.cost_usd, status: "complete" };
    case "error":
      return { ...turn, status: "error", error: joinErrors(turn.error, event.text) };
    case "saved":
      return event.turn; // the server's copy: structured references, final status, id for export
    default:
      return turn;
  }
}

export const turnExportUrl = (id, { format = "json", download = false } = {}) =>
  `/api/turns/${id}/export?format=${format}${download ? "&download=true" : ""}`;

/** Copy an answer as Markdown for pasting into another LLM. */
export async function copyTurnForLLM(id) {
  const fetchText = async () => {
    const res = await fetch(turnExportUrl(id, { format: "markdown" }));
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.text();
  };
  // ClipboardItem accepts a promise, so Safari still counts the click as the user gesture after the fetch.
  if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
    const blob = fetchText().then((text) => new Blob([text], { type: "text/plain" }));
    await navigator.clipboard.write([new ClipboardItem({ "text/plain": blob })]);
  } else {
    await navigator.clipboard.writeText(await fetchText());
  }
}
