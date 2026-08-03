from typing import List, Dict, Any
from core.db import db_client

async def list_dead_letter_entries(tenant_id: str = "default-tenant") -> List[Dict[str, Any]]:
    if not db_client.pool:
        await db_client.connect()
    async with db_client.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT d.task_id, d.document_id, d.agent_name, d.error, d.payload, d.created_at, dj.s3_uri FROM dead_letter_queues d LEFT JOIN document_jobs dj ON d.document_id = dj.document_id WHERE d.tenant_id = $1 ORDER BY d.created_at DESC LIMIT 100",
            tenant_id
        )
        import json
        return [
            {
                "task_id": r["task_id"],
                "document_id": r["document_id"],
                "agent_name": r["agent_name"],
                "error": r["error"],
                "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "s3_uri": r["s3_uri"]
            }
            for r in rows
        ]

async def list_hitl_requests(tenant_id: str = "default-tenant") -> List[Dict[str, Any]]:
    if not db_client.pool:
        await db_client.connect()
    async with db_client.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT h.id, h.document_id, h.status, h.error, h.payload, h.created_at, dj.s3_uri FROM hitl_requests h LEFT JOIN document_jobs dj ON h.document_id = dj.document_id WHERE h.tenant_id = $1 AND h.status = 'PENDING' ORDER BY h.created_at DESC LIMIT 100",
            tenant_id
        )
        import json
        return [
            {
                "id": r["id"],
                "document_id": r["document_id"],
                "status": r["status"],
                "error": r["error"],
                "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "s3_uri": r["s3_uri"]
            }
            for r in rows
        ]
