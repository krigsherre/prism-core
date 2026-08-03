import asyncio
import copy
import datetime
import json
import os
from typing import Any, Dict, List

import boto3
import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from botocore.config import Config
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from core.config import settings
from core.db import db_client
from utils.dlq_view import list_dead_letter_entries, list_hitl_requests

class HitlResolveRequest(BaseModel):
    id: str = ""
    tenant_id: str = "default-tenant"
    document_id: str
    patch_type: str = "jsonb"
    field_name: str = ""
    correct_value: str

class HitlDiscardRequest(BaseModel):
    id: str = ""
    document_id: str
    tenant_id: str = "default-tenant"

router = APIRouter(tags=["system"])

@router.get("/health")
async def health() -> JSONResponse:
    """Liveness probe for infrastructure monitoring."""
    return JSONResponse(content={"status": "ok", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})

@router.get("/api/dlq", response_model=List[Dict[str, Any]])
async def get_dead_letters(tenant_id: str = "default-tenant") -> List[Dict[str, Any]]:
    """Retrieve dead letter queues."""
    return await list_dead_letter_entries(tenant_id)

@router.get("/api/hitl", response_model=List[Dict[str, Any]])
async def get_hitl_requests(tenant_id: str = "default-tenant") -> List[Dict[str, Any]]:
    """Retrieve active HITL requests."""
    return await list_hitl_requests(tenant_id)

@router.post("/api/hitl/resolve")
async def resolve_hitl_request(payload: HitlResolveRequest):
    from core.db import db_client
    from utils.corrections import (
        dictionary_cdc_event,
        fetch_few_shot_corrections,
        persist_correction,
    )
    
    if not db_client.pool:
        await db_client.connect()
        
    r = redis.from_url(settings.redis_url)
    
    async with db_client.pool.acquire() as conn:
        hitl_row = await conn.fetchrow(
            "SELECT id, payload FROM hitl_requests WHERE document_id = $1", 
            payload.document_id
        )
        dlq_row = await conn.fetchrow(
            "SELECT task_id as id, payload FROM dead_letter_queues WHERE document_id = $1", 
            payload.document_id
        )
        
        row = hitl_row or dlq_row
        if not row:
            raise HTTPException(status_code=404, detail="HITL or DLQ request not found for this document")
            
        original_payload = row["payload"]
        if isinstance(original_payload, str):
            original_payload = json.loads(original_payload)

        before_snapshot = copy.deepcopy(original_payload)

        try:
            patched_data = json.loads(payload.correct_value)
            original_payload["extracted_data"] = patched_data
        except Exception:
            if payload.field_name and "extracted_data" in original_payload:
                original_payload["extracted_data"][payload.field_name] = payload.correct_value
            else:
                raise HTTPException(
                    status_code=400,
                    detail="correct_value must be JSON object/array or field_name must be set",
                )

        after_data = original_payload.get("extracted_data")

        try:
            correction = await persist_correction(
                conn,
                tenant_id=payload.tenant_id,
                document_id=payload.document_id,
                hitl_request_id=str(hitl_row["id"]) if hitl_row else "",
                original_payload=before_snapshot if isinstance(before_snapshot, dict) else {},
                after_data=after_data,
                field_name=payload.field_name,
            )
        except Exception as e:
            # Table may not be migrated yet — still resolve the document
            import structlog
            structlog.get_logger(__name__).warning("Failed to persist correction", error=str(e))
            correction = {"synonym_mappings": [], "id": None, "field_patches": []}

        producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        await producer.start()
        try:
            for mapping in correction.get("synonym_mappings") or []:
                event = dictionary_cdc_event(
                    tenant_id=payload.tenant_id,
                    target_table=original_payload.get("target_table") or "",
                    raw_label=mapping["raw_label"],
                    mapped_column=mapping["mapped_column"],
                )
                await producer.send_and_wait(
                    "dictionary_cdc",
                    key=payload.tenant_id.encode("utf-8"),
                    value=json.dumps(event).encode("utf-8"),
                )

            few_shots = []
            try:
                few_shots = await fetch_few_shot_corrections(
                    conn,
                    tenant_id=payload.tenant_id,
                    target_table=original_payload.get("target_table") or "",
                    limit=3,
                    critic_error=str(
                        (original_payload.get("unmapped_jsonb") or [{}])[0].get("critic_error")
                        if isinstance(original_payload.get("unmapped_jsonb"), list)
                        and original_payload.get("unmapped_jsonb")
                        else original_payload.get("error") or ""
                    ),
                )
            except Exception:
                few_shots = []

            original_payload["few_shot_examples"] = few_shots
            original_payload["from_hitl_correction"] = correction.get("id")

            await producer.send_and_wait(
                "raw_table_doms",
                key=payload.document_id.encode("utf-8"),
                value=json.dumps(original_payload).encode("utf-8")
            )
        finally:
            await producer.stop()
            
        if hitl_row:
            await conn.execute("DELETE FROM hitl_requests WHERE id = $1", hitl_row["id"])
            await r.delete(f"hitl:timeout:{payload.document_id}")
            await r.delete(f"hitl:payload:{payload.document_id}")
        if dlq_row:
            await conn.execute("DELETE FROM dead_letter_queues WHERE task_id = $1", dlq_row["id"])
            
    return {
        "status": "resolved",
        "document_id": payload.document_id,
        "correction_id": correction.get("id"),
        "synonyms_published": len(correction.get("synonym_mappings") or []),
        "field_patches": len(correction.get("field_patches") or []),
    }

@router.get("/api/corrections")
async def list_extraction_corrections(
    tenant_id: str = "default-tenant",
    target_table: str = "",
    limit: int = 50,
    unpromoted_only: bool = False,
):
    """List HITL learning records (extraction corrections)."""
    from core.db import db_client

    if not db_client.pool:
        await db_client.connect()

    limit = max(1, min(int(limit or 50), 200))
    clauses = ["tenant_id = $1"]
    args: List[Any] = [tenant_id]
    if target_table:
        args.append(target_table)
        clauses.append(f"target_table = ${len(args)}")
    if unpromoted_only:
        clauses.append("promoted_to_eval = false")
    where = " AND ".join(clauses)
    args.append(limit)
    query = f"""
        SELECT id, tenant_id, document_id, target_table, critic_error,
               field_patches, synonym_mappings, promoted_to_eval, created_at
        FROM extraction_corrections
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT ${len(args)}
    """
    try:
        async with db_client.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Corrections unavailable: {e}")

    return [
        {
            "id": r["id"],
            "tenant_id": r["tenant_id"],
            "document_id": r["document_id"],
            "target_table": r["target_table"],
            "critic_error": r["critic_error"],
            "field_patches": r["field_patches"],
            "synonym_mappings": r["synonym_mappings"],
            "promoted_to_eval": r["promoted_to_eval"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]

@router.post("/api/hitl/discard")
async def discard_hitl_request(payload: HitlDiscardRequest):
    from core.db import db_client
    import redis.asyncio as redis
    from aiokafka import AIOKafkaProducer
    
    if not db_client.pool:
        await db_client.connect()
        
    r = redis.from_url(settings.redis_url)
    
    async with db_client.pool.acquire() as conn:
        if payload.id:
            await conn.execute("DELETE FROM hitl_requests WHERE id = $1", payload.id)
            await conn.execute("DELETE FROM dead_letter_queues WHERE task_id = $1", payload.id)
        else:
            await conn.execute("DELETE FROM hitl_requests WHERE document_id = $1", payload.document_id)
            await conn.execute("DELETE FROM dead_letter_queues WHERE document_id = $1", payload.document_id)
        
        await r.delete(f"hitl:timeout:{payload.document_id}")
        await r.delete(f"hitl:payload:{payload.document_id}")

    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
    await producer.start()
    try:
        status_payload = {
            "document_id": payload.document_id,
            "tenant_id": payload.tenant_id,
            "sql_node_completed": True,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        await producer.send_and_wait(
            "document_status_events",
            json.dumps(status_payload).encode("utf-8"),
            key=payload.tenant_id.encode("utf-8")
        )
    finally:
        await producer.stop()
        
    return {"status": "discarded"}



@router.get("/api/documents/presign")
async def presign_document(s3_uri: str):
    """Generate a pre-signed URL for an S3 document."""
    if not s3_uri.startswith("s3://"):
        raise HTTPException(status_code=400, detail="Invalid S3 URI. Must start with s3://")
        
    path_parts = s3_uri[5:].split("/", 1)
    if len(path_parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid S3 URI format")
        
    bucket, key = path_parts
    
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    s3_client = boto3.client("s3", endpoint_url=endpoint_url)
    
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=3600
    )
    
    return {"url": url}

@router.get("/api/documents/jobs")
async def get_document_jobs(tenant_id: str = "default-tenant"):
    """Fetch active and recent document jobs for the tenant."""
    from core.db import db_client
    query = """
        SELECT document_id, filename, current_stage, status, error_message, updated_at, s3_uri
        FROM document_jobs
        WHERE tenant_id = $1
          AND (status IN ('PENDING', 'IN_PROGRESS', 'EXTRACTING')
               OR updated_at > NOW() - INTERVAL '24 hours')
        ORDER BY updated_at DESC
        LIMIT 50
    """
    if not db_client.pool:
        await db_client.connect()
    
    async with db_client.pool.acquire() as conn:
        rows = await conn.fetch(query, tenant_id)
        
    return [
        {
            "document_id": r["document_id"],
            "filename": r["filename"],
            "current_stage": r["current_stage"],
            "status": r["status"],
            "error_message": r["error_message"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "s3_uri": r["s3_uri"]
        }
        for r in rows
    ]

@router.post("/api/documents/retry/{document_id}")
async def retry_document_job(document_id: str, tenant_id: str = "default-tenant"):
    """Bypass triage-worker deduplication by pushing an IngestEvent directly to the GPU extractor."""

    query = """
        SELECT document_id, filename, s3_uri, file_hash 
        FROM document_jobs 
        WHERE document_id = $1 AND tenant_id = $2
    """
    
    if not db_client.pool:
        await db_client.connect()
        
    async with db_client.pool.acquire() as conn:
        row = await conn.fetchrow(query, document_id, tenant_id)
        
    if not row:
        raise HTTPException(status_code=404, detail="Document job not found")
        
    if not row["s3_uri"]:
        raise HTTPException(status_code=400, detail="Cannot retry: missing s3_uri for this document")

    payload = {
        "event_id": row["document_id"],
        "tenant_id": tenant_id,
        "s3_uri": row["s3_uri"],
        "file_hash_sha256": row["file_hash"] or "",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "metadata": {
            "original_filename": row["filename"]
        }
    }

    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
    await producer.start()
    try:
        await producer.send_and_wait(
            "gpu_processing_queue",
            json.dumps(payload).encode("utf-8"),
            key=tenant_id.encode("utf-8")
        )
    finally:
        await producer.stop()

    return {"message": "Job sent directly to GPU processing queue as JSON fallback."}

@router.get("/api/documents/status/stream")
async def document_status_stream(request: Request, tenant_id: str = "default-tenant"):
    """SSE endpoint for real-time document ingestion updates."""
    from core.broadcaster import status_broadcaster
    import json
    
    async def event_generator():
        q = status_broadcaster.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(q.get(), timeout=1.0)
                    
                    try:
                        data = json.loads(message)
                        if data.get("tenant_id") == tenant_id:
                            yield f"data: {message}\n\n"
                    except json.JSONDecodeError:
                        pass
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            status_broadcaster.unsubscribe(q)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

@router.get("/api/documents/content")
async def get_document_content(s3_uri: str, disposition: str = "inline"):
    """Stream an S3 document directly to bypass CORS.

    disposition=inline  → open in browser/PDF viewer (default)
    disposition=attachment → force download
    """
    if not s3_uri.startswith("s3://"):
        raise HTTPException(status_code=400, detail="Invalid S3 URI. Must start with s3://")
        
    path_parts = s3_uri[5:].split("/", 1)
    if len(path_parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid S3 URI format")
        
    bucket, key = path_parts
    filename = key.rsplit("/", 1)[-1] or "document.pdf"
    
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    region_name = os.environ.get("AWS_REGION", "ap-south-1")
    
    s3_client = boto3.client(
        's3', 
        endpoint_url=endpoint_url, 
        region_name=region_name,
        config=Config(signature_version='s3v4')
    )
    
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        def iterfile():
            yield from response['Body'].iter_chunks(chunk_size=1024 * 1024)

        disp = "attachment" if disposition.lower() == "attachment" else "inline"
        headers = {
            "Content-Disposition": f'{disp}; filename="{filename}"',
            "Cache-Control": "public, max-age=31536000, immutable",
        }
            
        return StreamingResponse(
            iterfile(), 
            media_type=response.get('ContentType', 'application/pdf'),
            headers=headers,
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found or error accessing S3: {str(e)}")

@router.get("/api/documents/{document_id}")
async def get_document_meta(document_id: str, tenant_id: str = "default-tenant"):
    """Resolve a document_id to metadata (including s3_uri) for the in-app viewer.

    Registered after static /api/documents/* routes so paths like
    /content and /jobs are not captured by this parameter.
    """
    from core.db import db_client
    query = """
        SELECT document_id, filename, s3_uri, status, current_stage
        FROM document_jobs
        WHERE document_id = $1 AND tenant_id = $2
        LIMIT 1
    """
    if not db_client.pool:
        await db_client.connect()

    async with db_client.pool.acquire() as conn:
        row = await conn.fetchrow(query, document_id, tenant_id)

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "document_id": row["document_id"],
        "filename": row["filename"],
        "s3_uri": row["s3_uri"],
        "status": row["status"],
        "current_stage": row["current_stage"],
    }