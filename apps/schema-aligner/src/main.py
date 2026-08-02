import asyncio
import structlog
import logging
from opentelemetry import trace
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from core.alignment import WaterfallAlignmentStrategy
from kafka.consumers import DictionaryCDCConsumer, RawTableDOMConsumer, SchemaCDCConsumer
from api.routes import router
from config.settings import settings


def configure_logging() -> None:
    """Configures structured logging with OpenTelemetry trace correlation."""
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

configure_logging()
logger = structlog.get_logger(__name__)


def create_application() -> FastAPI:
    """Application factory pattern for the Schema Aligner microservice."""
    alignment_strategy = WaterfallAlignmentStrategy()
    
    schema_consumer = SchemaCDCConsumer(alignment_strategy)
    dictionary_consumer = DictionaryCDCConsumer(alignment_strategy)
    raw_table_consumer = RawTableDOMConsumer(alignment_strategy)
    
    consumer_tasks = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting schema-aligner microservice...")
        tasks = [
            asyncio.create_task(schema_consumer.run()),
            asyncio.create_task(dictionary_consumer.run()),
            asyncio.create_task(raw_table_consumer.run())
        ]
        consumer_tasks.extend(tasks)
        
        yield
        
        logger.info("Shutting down schema-aligner microservice, cancelling background tasks...")
        for task in consumer_tasks:
            task.cancel()
            
        await asyncio.gather(*consumer_tasks, return_exceptions=True)
        logger.info("Shutdown complete.")

    app = FastAPI(title="Schema Aligner Microservice", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_application()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)