import asyncio
import structlog
import logging
from opentelemetry import trace

from kafka.cdc.observer import DebeziumObserver
from kafka.consumers.auto_promote import AutoPromoteConsumer
from kafka.consumers.aligned_consumer import AlignedSQLConsumer
from kafka.consumers.bifurcation import BifurcationConsumer
from kafka.consumers.status_consumer import StatusConsumer
from kafka.consumers.system_dlq import SystemDlqConsumer
from kafka.consumers.hitl_consumer import HitlConsumer

from repositories.sql_repo import SQLRepository
from repositories.qdrant_repo import QdrantRepository

def otel_processor(logger, log_method, event_dict):
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        otel_processor,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = structlog.get_logger(__name__)


async def main():
    logger.info("Initializing Storage & CDC Worker")

    sql_repo = SQLRepository()
    qdrant_repo = QdrantRepository()

    await _init_qdrant(qdrant_repo)
    await _init_database()
    await _run_consumers(sql_repo, qdrant_repo)


async def _init_qdrant(qdrant_repo: QdrantRepository) -> None:
    try:
        await qdrant_repo.initialize_collection()
    except Exception as e:
        logger.error("Failed to initialize Qdrant", error=str(e))


async def _init_database() -> None:
    try:
        from db.postgres import engine
        from db.models import Base
        from sqlalchemy import text
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
            await conn.execute(text("""
                CREATE OR REPLACE FUNCTION notify_document_job_update()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_notify(
                        'document_status_updates',
                        json_build_object(
                            'document_id', NEW.document_id,
                            'tenant_id', NEW.tenant_id,
                            'filename', NEW.filename,
                            'current_stage', NEW.current_stage,
                            'status', NEW.status,
                            'error_message', NEW.error_message,
                            'updated_at', NEW.updated_at,
                            's3_uri', NEW.s3_uri
                        )::text
                    );
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """))
            await conn.execute(text("DROP TRIGGER IF EXISTS trigger_document_job_update ON document_jobs;"))
            await conn.execute(text("""
                CREATE TRIGGER trigger_document_job_update
                AFTER INSERT OR UPDATE ON document_jobs
                FOR EACH ROW
                EXECUTE FUNCTION notify_document_job_update();
            """))
            logger.info("Database tables and triggers verified/created")
            
    except Exception as e:
        logger.error("Failed to initialize tables/triggers", error=str(e))
        
    try:
        from db.views import generate_schema_views
        await generate_schema_views()
    except Exception as e:
        logger.error("Failed to generate views", error=str(e))


async def _run_consumers(sql_repo: SQLRepository, qdrant_repo: QdrantRepository) -> None:
    from db.postgres import AsyncSessionLocal
    
    status_consumer = StatusConsumer(AsyncSessionLocal)
    system_dlq_consumer = SystemDlqConsumer(AsyncSessionLocal)
    hitl_consumer = HitlConsumer(AsyncSessionLocal)
    bifurcation = BifurcationConsumer(sql_repo, qdrant_repo)
    aligned_consumer = AlignedSQLConsumer(sql_repo)
    auto_promote_consumer = AutoPromoteConsumer(sql_repo)
    cdc_observer = DebeziumObserver(qdrant_repo)
    
    await asyncio.gather(
        status_consumer.run(),
        system_dlq_consumer.run(),
        hitl_consumer.run(),
        bifurcation.run(),
        aligned_consumer.run(),
        auto_promote_consumer.run(),
        cdc_observer.run()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped")