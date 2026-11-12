# info-center

A chat GUI for Claude Code. React + MUI frontend, FastAPI backend, PostgreSQL.

The backend drives Claude Code through the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview),
so each chat is a real Claude Code session: it can read and edit files, run commands, and search the web
inside `./workspace`.

## Setup

```bash
cp .env.example .env
claude setup-token            # Pro/Max plan: paste the printed token into CLAUDE_CODE_OAUTH_TOKEN in .env
docker compose -f docker-compose.dev.yml up --build
```

Credentials, set one in `.env`:

- **`CLAUDE_CODE_OAUTH_TOKEN`**: uses your Claude Pro/Max subscription and its usage limits. `claude setup-token`
  creates a one-year token. For personal use only; keep it out of git (`.env` is ignored).
- **`ANTHROPIC_API_KEY`**: pay-as-you-go API billing, with a key from the [Claude Console](https://platform.claude.com/).
  Per-reply cost is shown only in this mode.

| Service  | URL                          |
| -------- | ---------------------------- |
| Chat UI  | http://localhost:5678        |
| API      | http://localhost:8765/api    |
| API docs | http://localhost:8765/docs   |
| MCP      | http://localhost:8765/mcp    |
| Public API docs | http://localhost:8765/api/v1/docs |
| Postgres | localhost:5432 (app/app/app) |
| pgweb    | http://localhost:8081        |

## How it works

- `POST /api/conversations/{id}/messages` runs one Claude Code turn and streams it back as server-sent events
  (text deltas, tool calls, tool results, final cost).
- Each question and answer is one row in `turns` (Postgres): question, model, mode (normal / research), the tool
  activity, status, and `metadata`: the answer as plain Markdown, its citation and confidence spans
  (`annotations`, as code point offsets) and its structured references, stored as the full export JSON. Each conversation keeps its Claude Code
  session id, and the next message resumes that session. Session transcripts live in the `claude-config` volume.
- Export an answer for other LLMs or tools: `GET /api/turns/{id}/export` (JSON, `schema_version` 2) or
  `?format=markdown`, and a whole chat with `GET /api/conversations/{id}/export`. Each answer in the UI has
  **Copy content for LLM** (the answer's Markdown, `metadata.content`, as text) and **Copy json metadata** (the
  whole `metadata` column as JSON), both to the clipboard. The export JSON is built once when the
  answer is saved and stored in `turns.metadata`; the endpoints and the chat UI read that stored copy, so
  reference levels are the Source list's ratings at answer time. Format details: `backend/app/answers.py`.
- Claude Code works in `./workspace` (mounted at `/workspace` in the backend container).
- Tools are pre-approved (`permission_mode="dontAsk"`). Default set: Read, Write, Edit, Glob, Grep, Bash, WebSearch,
  WebFetch, TodoWrite. Override with `CLAUDE_ALLOWED_TOOLS='["Read","Glob","Grep"]'`. This list isn't a hard limit:
  Claude Code still runs commands it considers harmless (like `echo`) without asking. Bash runs inside the backend
  container, not on your machine.
- Answers run as background jobs (`backend/app/jobs.py`): closing the page doesn't stop one, and reopening the chat
  shows it live from the start. At most `MAX_CONCURRENT_TURNS` run at once; the rest wait. The Stop button cancels
  the answer (`POST /api/turns/{id}/cancel`); the partial reply is kept. Answers cut off by a server restart are
  marked as errors on the next start.

## Integrations (MCP and the public API)

Other systems can use this app for research. Create an **integration** on the Integrations tab: it gets an API
key (shown once), permissions (Research: start and cancel; Read: get results and search past answers) and an
optional daily question limit. Turning it off, creating a new key or deleting it cuts the old key off at once.
Each integration only sees its own chats, which also appear in the chat list ("via <name>").

- **MCP** at `/mcp` (Streamable HTTP, stateless), for AI agents. The handshake sends instructions on how to use
  it, and the tool list only shows what the key may do: `start_research`, `get_research`, `search_answers`,
  `cancel_research`. With Claude Code:
  `claude mcp add --transport http info-center http://localhost:8765/mcp --header "Authorization: Bearer <key>"`
- **REST** at `/api/v1` with its own docs (`/api/v1/docs`), listing only the public endpoints. `GET /api/v1/` (no
  key needed) describes the API and how to connect. Research runs in the background: `POST /api/v1/research`,
  then poll `GET /api/v1/research/{job_id}` until it's done.
- Every request needs `Authorization: Bearer <key>`. Questions from integrations can only use
  `INTEGRATION_ALLOWED_TOOLS` (default WebSearch and WebFetch); Claude doesn't get Bash or file tools at all.
- Code: `backend/app/integrations.py` (keys, permissions, limits, shared research functions),
  `backend/app/mcp_server.py`, `backend/app/api_v1.py`.

Before putting this on a public server: the chat UI and `/api/*` have no login (only integrations use keys), so
put the UI behind authentication; serve over HTTPS; use `ANTHROPIC_API_KEY` rather than a personal subscription
token for a service others use; remove or protect pgweb; and run one backend process (jobs live in that process).

## Development

Both apps hot reload: edit files under `frontend/src` (Vite HMR) or `backend/app` (uvicorn `--reload`).
The frontend calls the API via `/api`, which Vite proxies to the backend.

After changing dependencies (`package.json` or `requirements.txt`), rebuild with a fresh `node_modules` volume:

```bash
docker compose -f docker-compose.dev.yml up --build -V
```

Reset the database and Claude sessions: `docker compose -f docker-compose.dev.yml down -v`
