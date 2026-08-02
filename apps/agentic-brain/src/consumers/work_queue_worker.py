"""Durable agent work queue using Postgres SKIP LOCKED claiming."""
from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import Any, Dict, Optional

import structlog
from langchain_core.messages import HumanMessage

from core.config import settings
from core.db import db_client

logger = structlog.get_logger(__name__)


def _worker_id() -> str:
    if settings.work_queue_worker_id:
        return settings.work_queue_worker_id
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


CLAIM_SQL = """
WITH next_task AS (
    SELECT id
    FROM agent_tasks
    WHERE status = 'QUEUED'
       OR (
            status = 'RUNNING'
            AND locked_at IS NOT NULL
            AND locked_at < NOW() - ($2 * INTERVAL '1 second')
       )
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE agent_tasks t
SET status = 'RUNNING',
    locked_at = NOW(),
    locked_by = $1,
    updated_at = NOW()
FROM next_task
WHERE t.id = next_task.id
RETURNING t.id, t.tenant_id, t.agent_id, t.document_id, t.prompt,
          (SELECT system_prompt FROM agents a WHERE a.id = t.agent_id) AS system_prompt
"""


async def claim_next_task(worker_id: str) -> Optional[Dict[str, Any]]:
    if not db_client.pool:
        await db_client.connect()
    async with db_client.pool.acquire() as conn:
        row = await conn.fetchrow(CLAIM_SQL, worker_id, settings.work_queue_stale_seconds)
    if not row:
        return None
    return dict(row)


async def complete_task(task_id: str, result: str) -> None:
    async with db_client.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE agent_tasks
            SET status = 'COMPLETED', result = $1, locked_at = NULL, locked_by = NULL, updated_at = NOW()
            WHERE id = $2
            """,
            result,
            task_id,
        )


async def fail_task(task_id: str, error: str) -> None:
    async with db_client.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE agent_tasks
            SET status = 'FAILED', result = $1, locked_at = NULL, locked_by = NULL, updated_at = NOW()
            WHERE id = $2
            """,
            error,
            task_id,
        )


async def execute_claimed_task(task: Dict[str, Any]) -> None:
    task_id = task["id"]
    tenant_id = task["tenant_id"]
    document_id = task.get("document_id") or ""
    prompt = task.get("prompt") or ""
    system_prompt = task.get("system_prompt") or ""

    if not prompt:
        await fail_task(task_id, "Task missing prompt; cannot execute")
        return

    state = {
        "messages": [HumanMessage(content=prompt)],
        "tenant_id": tenant_id,
        "document_id": document_id,
        "system_prompt": system_prompt,
        "is_complex": True,
        "required_modalities": [],
        "target_task": "",
        "sql_query": "",
        "cypher_query": "",
        "vector_query": "",
        "sql_result": "",
        "cypher_result": "",
        "vector_result": "",
        "retries": 0,
        "error_message": "",
        "final_answer": "",
        "references": [],
    }

    graph = __import__("graph.workflow", fromlist=["get_brain_graph"]).get_brain_graph()
    config = {"configurable": {"thread_id": task_id}}
    final_state = await graph.ainvoke(state, config=config)
    result = final_state.get("final_answer", "No answer generated.")
    await complete_task(task_id, result)


class WorkQueueWorker:
    """Polls Postgres for QUEUED agent_tasks and executes them via brain_graph."""

    def __init__(self) -> None:
        self._worker_id = _worker_id()
        self._stopped = False

    async def run(self) -> None:
        logger.info("WorkQueueWorker started", worker_id=self._worker_id)
        while not self._stopped:
            try:
                task = await claim_next_task(self._worker_id)
                if not task:
                    await asyncio.sleep(settings.work_queue_poll_seconds)
                    continue
                logger.info("Claimed agent task", task_id=task["id"], tenant_id=task["tenant_id"])
                try:
                    await execute_claimed_task(task)
                    logger.info("Completed agent task", task_id=task["id"])
                except Exception as e:
                    logger.error("Agent task failed", task_id=task["id"], error=str(e))
                    await fail_task(task["id"], str(e))
            except asyncio.CancelledError:
                logger.info("WorkQueueWorker cancelled")
                raise
            except Exception as e:
                logger.error("WorkQueueWorker loop error", error=str(e))
                await asyncio.sleep(settings.work_queue_poll_seconds)

    def stop(self) -> None:
        self._stopped = True
