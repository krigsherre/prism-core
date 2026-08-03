from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    kafka_broker: str = "localhost:9092"
    kafka_output_topic: str = "aligned_sql_payloads"
    port: int = 8001
    chunk_size_rows: int = 10
    fuzzy_match_threshold: int = 80
    max_concurrent_inferences: int = 5
    max_reflexion_attempts: int = 3
    confidence_auto_promote_min: float = 0.85
    confidence_review_min: float = 0.55
    doc_router_min_score: float = 1.5
    tenant_synonyms_path: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
