from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    kafka_broker: str = "localhost:9092"
    s3_endpoint: str | None = None
    gotenberg_url: str = "http://gotenberg:3000/forms/libreoffice/convert"
    port: int = 8000

    vllm_paddleocr_url: str = "http://vllm-paddleocr:8003/v1"
    vllm_docling_url: str = "http://vllm-docling:8004/v1"
    docling_layout_url: str = "http://docling-layout:8002"
    
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    chunk_size_pages: int = 5
    table_span_threshold_bottom: float = 0.85
    table_span_threshold_top: float = 0.15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
