import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
import boto3
from typing import Tuple
from broker.consumer import KafkaConsumerService
from broker.s3_cleanup import S3CleanupConsumer
from core.service import ExtractionService
from core.engine import DynamicBatcher
from core.dom.preprocessor import OmniPreprocessor
from core.ml.layout import LayoutSlicer
from core.ml.adapters import ExtractorFactory
from core.dom.post_processor import DOMPostProcessor
from api.routes import router as api_router

import structlog
from opentelemetry import trace

from config.settings import settings

def setup_logging():
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


setup_logging()
logger = structlog.get_logger(__name__)


def setup_dependencies() -> Tuple[DynamicBatcher, KafkaConsumerService, S3CleanupConsumer]:
    """Wire S3, extraction pipeline, Kafka consumer, and cleanup worker."""
    logger.info("Initializing dependency graph")
    if settings.s3_endpoint:
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
    else:
        s3_client = boto3.client("s3", region_name=settings.aws_region)

    preprocessor = OmniPreprocessor()
    layout_slicer = LayoutSlicer()
    extractor_factory = ExtractorFactory()
    post_processor = DOMPostProcessor()
    dynamic_batcher = DynamicBatcher(extractor_factory)

    extraction_service = ExtractionService(
        s3_client=s3_client,
        preprocessor=preprocessor,
        layout_slicer=layout_slicer,
        extractor_factory=extractor_factory,
        post_processor=post_processor,
        dynamic_batcher=dynamic_batcher,
    )

    kafka_consumer_service = KafkaConsumerService(extraction_service=extraction_service)
    cleanup_consumer = S3CleanupConsumer(s3_client)

    return dynamic_batcher, kafka_consumer_service, cleanup_consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    batcher, kafka_service, cleanup_consumer = setup_dependencies()
    
    batcher.start()
    kafka_task = asyncio.create_task(kafka_service.start())
    cleanup_task = asyncio.create_task(cleanup_consumer.run())
    
    yield
    
    logger.info("Initiating graceful shutdown...")
    cleanup_task.cancel()
    kafka_task.cancel()
    await kafka_service.stop()
    await batcher.stop()
    await asyncio.gather(cleanup_task, kafka_task, return_exceptions=True)


app = FastAPI(title="GPU Extractor Worker", lifespan=lifespan)
app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
