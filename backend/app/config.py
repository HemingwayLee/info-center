from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    # "null" is the origin of an HTML file opened from disk (e.g. a local MCP test client).
    cors_origins: list[str] = ["http://localhost:5678", "null"]
    # Also allow any port on localhost (and *.localhost), 127.0.0.1, 0.0.0.0 and [::1], for local test pages.
    cors_origin_regex: str | None = r"^https?://(([^/:]+\.)?localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d+)?$"

    # Claude Code (Agent SDK) settings
    claude_workspace: str = "/workspace"
    claude_default_model: str = "claude-opus-5-5"
    claude_allowed_tools: list[str] = [
        "Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch", "TodoWrite",
    ]
    # Largest single message accepted from the Claude Code CLI (SDK default is 1 MB).
    claude_max_buffer_bytes: int = 64 * 1024 * 1024
    # Tool output longer than this is cut off in the chat UI and database.
    tool_result_display_chars: int = 20_000

    # Answers run as background jobs; at most this many Claude Code processes run at once, the rest wait.
    max_concurrent_turns: int = 3
    # Tools Claude may use for questions from integrations (MCP and /api/v1): research only, no shell or files.
    integration_allowed_tools: list[str] = ["WebSearch", "WebFetch"]
    # How other systems reach this backend; shown in the Integrations tab and the /api/v1 welcome.
    public_base_url: str = "http://localhost:8765"


settings = Settings()
