import asyncio

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace

from api.routes import agents, chat, system
from consumers.dlq_consumer import DLQConsumer
from consumers.graph_consumer import GraphConsumer
from consumers.work_queue_worker import WorkQueueWorker
from core.config import settings
from core.db import db_client
from core.neo4j_client import neo4j_client
from graph.workflow import close_brain_graph, init_brain_graph

background_tasks = set()

def otel_processor(logger, log_method, event_dict):
    """Inject OpenTelemetry trace and span IDs into log entries."""
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

processors = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    otel_processor,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]

if settings.environment == "production":
    processors.append(structlog.processors.JSONRenderer())
else:
    processors.append(structlog.dev.ConsoleRenderer())

structlog.configure(
    processors=processors,
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("api")

def create_app() -> FastAPI:
    """Application factory for FastAPI."""
    app = FastAPI(
        title="Agentic Brain Orchestrator",
        description="Deterministic Task Orchestration and Tri-Modal RAG Engine",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router)
    app.include_router(system.router)
    app.include_router(agents.router)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled Exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"message": "Internal Server Error", "details": str(exc) if settings.environment != "production" else None},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("Validation Error", errors=exc.errors(), path=request.url.path)
        return JSONResponse(
            status_code=422,
            content={"message": "Validation Error", "details": exc.errors()},
        )

    @app.on_event("startup")
    async def startup_event():
        logger.info("Starting Agentic Brain", environment=settings.environment)
        await db_client.connect()
        await init_brain_graph(settings.psycopg_checkpoint_url)

        dlq_task = asyncio.create_task(DLQConsumer().run())
        graph_task = asyncio.create_task(GraphConsumer().run())
        work_task = asyncio.create_task(WorkQueueWorker().run())
        background_tasks.add(dlq_task)
        background_tasks.add(graph_task)
        background_tasks.add(work_task)
        dlq_task.add_done_callback(background_tasks.discard)
        graph_task.add_done_callback(background_tasks.discard)
        work_task.add_done_callback(background_tasks.discard)

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Shutting down Agentic Brain")

        for task in background_tasks:
            task.cancel()
        await close_brain_graph()
        await db_client.close()
        await neo4j_client.close()
        
    return app

app = create_app()
