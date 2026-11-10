from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    cors_origins: list[str] = ["http://localhost:5678"]

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


settings = Settings()
