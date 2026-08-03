from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from aiokafka import AIOKafkaClient, AIOKafkaProducer
from config.settings import settings
import json
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


class ApproveGenericRequest(BaseModel):
    document_id: str
    node_id: str
    target_table: str
    unmapped_rows: List[Dict[str, Any]]
    tenant_id: str = "default-tenant"


class DivertRagRequest(BaseModel):
    document_id: str
    node_id: str
    markdown_content: str
    parent_section_text: Optional[str] = ""
    tenant_id: str = "default-tenant"


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    client = AIOKafkaClient(bootstrap_servers=settings.kafka_broker)
    try:
        await client.bootstrap()
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Kafka unreachable: {str(e)}")
    finally:
        await client.close()


@router.post("/api/v1/hitl/approve-generic")
async def approve_generic(req: ApproveGenericRequest):
    """Approve an unmapped table as a generic JSONB payload for Postgres."""
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
    try:
        await producer.start()
        payload = {
            "document_id": req.document_id,
            "node_id": req.node_id,
            "target_table": req.target_table,
            "mapping_status": "GENERIC_APPROVED",
            "strict_columns": [],
            "unmapped_jsonb": req.unmapped_rows,
            "tenant_id": req.tenant_id,
        }
        await producer.send_and_wait(
            settings.kafka_output_topic,
            json.dumps(payload).encode("utf-8")
        )
        logger.info("Approved table as generic JSONB", document_id=req.document_id, node_id=req.node_id)
        return {"status": "success", "mapping_status": "GENERIC_APPROVED"}
    except Exception as e:
        logger.error("Failed to approve generic table", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await producer.stop()


@router.post("/api/v1/hitl/divert-rag")
async def divert_rag(req: DivertRagRequest):
    """Divert an unmapped table markdown directly to Qdrant (vector) & Neo4j (graph)."""
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
    try:
        await producer.start()
        payload = {
            "document_id": req.document_id,
            "node_id": req.node_id,
            "divert_to_rag": True,
            "markdown_content": req.markdown_content,
            "parent_section_text": req.parent_section_text or "",
            "tenant_id": req.tenant_id,
        }
        await producer.send_and_wait(
            settings.kafka_output_topic,
            json.dumps(payload).encode("utf-8")
        )
        logger.info("Diverted unmapped table to RAG", document_id=req.document_id, node_id=req.node_id)
        return {"status": "success", "diverted": True}
    except Exception as e:
        logger.error("Failed to divert table to RAG", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await producer.stop()

