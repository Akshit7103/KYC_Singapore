"""Application configuration.

Values come from real environment variables first, falling back to a local
`.env` file during development. In a deployed environment (Render) there is no
`.env` file — everything is set in the dashboard.
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OPENAI_API_KEY: str = ""
    OPENAI_VISION_MODEL: str = "gpt-4o"
    RENDER_DPI: int = 150
    MAX_PAGES_PER_DOC: int = 6

    # Credentials are deliberately empty by default. The app refuses to start
    # without a password rather than falling back to a value baked into source.
    AUTH_USERNAME: str = "admin"
    AUTH_PASSWORD: str = ""

    # Where the SQLite database and uploaded documents live. Leave unset for a
    # local ./data directory; point it at a mounted disk (e.g. /var/data) to
    # survive redeploys.
    DATA_DIR: str = ""

    # Session cookies are HTTPS-only unless explicitly relaxed for local dev.
    COOKIE_SECURE: bool = True

    @property
    def data_dir(self) -> Path:
        p = Path(self.DATA_DIR) if self.DATA_DIR else BASE_DIR / "data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def storage_dir(self) -> Path:
        p = self.data_dir / "storage"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kyc.db"


settings = Settings()


def check_required() -> None:
    """Fail fast on a misconfigured deploy instead of booting insecurely."""
    if not settings.AUTH_PASSWORD:
        raise RuntimeError(
            "AUTH_PASSWORD is not set. Set it as an environment variable "
            "(or in .env for local development) before starting the app."
        )


def is_local() -> bool:
    """True when running outside a Render deployment."""
    return not os.environ.get("RENDER")
