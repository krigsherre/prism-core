from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_APP_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = (
    Path(__file__).resolve().parents[4]
    if len(Path(__file__).resolve().parents) > 4
    else _APP_DIR
)


class Settings(BaseSettings):
    """Centralized configuration for Storage Sync."""

    kafka_broker: str = "localhost:9092"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "prism"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/prism"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = "test-qdrant-key-12345"
    cdc_max_concurrent_inferences: int = 5
    kafka_consumer_group_bifurcation: str = "bifurcation-consumer-group"
    kafka_consumer_group_aligned: str = "aligned-consumer-group"
    kafka_consumer_group_auto_promote: str = "auto-promote-consumer-group"
    kafka_consumer_group_system_dlq: str = "system-dlq-consumer-group"
    qdrant_collection_name: str = "document_chunks"
    chunk_assemble_timeout_seconds: float = 900.0

    model_config = SettingsConfigDict(
        env_file=(
            str(_APP_DIR / ".env"),
            str(_REPO_ROOT / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def resolve_database_url(self) -> "Settings":
        url = self.database_url
        if not url or "${" in url:
            url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        if not Path("/.dockerenv").exists():
            url = url.replace("@postgres:", "@localhost:")
        object.__setattr__(self, "database_url", url)
        return self


settings = Settings()
