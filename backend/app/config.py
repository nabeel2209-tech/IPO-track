"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SQLite by default so the project runs with zero setup; set a Postgres URL in production.
    database_url: str = f"sqlite:///{DATA_DIR / 'ipo.db'}"

    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:5173"

    # AI question answering (optional). Without a key the /api/ask endpoint returns 503.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"
    ask_max_question_chars: int = 300
    ask_per_ip_per_day: int = 15
    ask_global_per_day: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
