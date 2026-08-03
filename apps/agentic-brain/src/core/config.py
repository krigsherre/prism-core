import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    kafka_broker: str = "kafka:9092"
    kafka_max_retries: int = 5
    
    redis_url: str = "redis://redis:6379"
    redis_max_retries: int = 5
    
    database_url: str = "postgresql://postgres:postgres@postgres:5432/prism"
    checkpoint_database_url: str = ""  # psycopg URL for LangGraph checkpoints
    db_pool_size: int = 20
    db_max_retries: int = 5

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "document_chunks"
    embeddings_api_url: str = "http://embeddings-server:80/embed"
    reranker_api_url: str = "http://reranker-server:80/rerank"

    llm_provider: str = "anthropic"
    llm_model: str = "claude-haiku-4-5-20251001"
    frontier_llm_provider: str = "anthropic"
    frontier_llm_model: str = "claude-haiku-4-5-20251001"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    
    max_retries: int = 3
    retry_expiry_seconds: int = 3600
    hitl_timeout_seconds: int = 48 * 3600
    work_queue_poll_seconds: float = 2.0
    work_queue_stale_seconds: int = 900
    work_queue_worker_id: str = ""
    
    environment: str = "development"
    allowed_origins: list[str] = ["*"]
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    @property
    def psycopg_checkpoint_url(self) -> str:
        """LangGraph Postgres saver expects a psycopg-compatible URL."""
        if self.checkpoint_database_url:
            return self.checkpoint_database_url
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return "postgresql://" + url.split("://", 1)[1]
        return url

settings = Settings()

if settings.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
if settings.openai_api_key and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
