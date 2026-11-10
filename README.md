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
| Postgres | localhost:5432 (app/app/app) |

## How it works

- `POST /api/conversations/{id}/messages` runs one Claude Code turn and streams it back as server-sent events
  (text deltas, tool calls, tool results, final cost).
- Each question and answer is one row in `turns` (Postgres): question, model, mode (normal / research), the answer
  as Markdown, structured references, the tool activity, and status. Each conversation keeps its Claude Code
  session id, and the next message resumes that session. Session transcripts live in the `claude-config` volume.
- Export an answer for other LLMs or tools: `GET /api/turns/{id}/export` (JSON, `schema_version` 1) or
  `?format=markdown`, and a whole chat with `GET /api/conversations/{id}/export`. Each answer in the UI has
  **Copy for LLM** (Markdown to clipboard) and **Export** (JSON download). Format details: `backend/app/answers.py`.
- Claude Code works in `./workspace` (mounted at `/workspace` in the backend container).
- Tools are pre-approved and anything else is denied (`permission_mode="dontAsk"`). Default set: Read, Write,
  Edit, Glob, Grep, Bash, WebSearch, WebFetch, TodoWrite. Override with `CLAUDE_ALLOWED_TOOLS='["Read","Glob","Grep"]'`.
  Bash runs inside the backend container, not on your machine.
- The Stop button aborts the stream, which stops Claude Code; the partial reply is kept.

## Development

Both apps hot reload: edit files under `frontend/src` (Vite HMR) or `backend/app` (uvicorn `--reload`).
The frontend calls the API via `/api`, which Vite proxies to the backend.

After changing dependencies (`package.json` or `requirements.txt`), rebuild with a fresh `node_modules` volume:

```bash
docker compose -f docker-compose.dev.yml up --build -V
```

Reset the database and Claude sessions: `docker compose -f docker-compose.dev.yml down -v`
