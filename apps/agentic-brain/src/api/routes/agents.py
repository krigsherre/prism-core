from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid

from api.deps import get_current_user
from core.db import db_client
from core.employee_personas import list_personas

router = APIRouter(tags=["agents"])


@router.get("/api/agents/personas")
async def get_employee_personas():
    """Return available pre-configured AI Employee Personas."""
    return list_personas()


class AgentCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    system_prompt: str

class AgentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    system_prompt: str
    created_at: str

class WorkRequest(BaseModel):
    agent_id: str
    document_id: Optional[str] = None
    prompt: str

class WorkResponse(BaseModel):
    task_id: str
    status: str

@router.get("/api/agents", response_model=List[AgentResponse])
async def list_agents(user: Dict[str, Any] = Depends(get_current_user)):
    tenant_id = user.get("tenant_id", "default-tenant")
    if not db_client.pool:
        await db_client.connect()
        
    query = "SELECT id, name, description, system_prompt, created_at FROM agents WHERE tenant_id = $1 ORDER BY created_at DESC"
    async with db_client.pool.acquire() as conn:
        rows = await conn.fetch(query, tenant_id)
        
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "system_prompt": r["system_prompt"],
            "created_at": r["created_at"].isoformat()
        }
        for r in rows
    ]

@router.post("/api/agents", response_model=AgentResponse)
async def create_agent(req: AgentCreateRequest, user: Dict[str, Any] = Depends(get_current_user)):
    tenant_id = user.get("tenant_id", "default-tenant")
    agent_id = str(uuid.uuid4())
    
    if not db_client.pool:
        await db_client.connect()
        
    query = """
        INSERT INTO agents (id, tenant_id, name, description, system_prompt)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING created_at
    """
    async with db_client.pool.acquire() as conn:
        created_at = await conn.fetchval(query, agent_id, tenant_id, req.name, req.description, req.system_prompt)
        
    return {
        "id": agent_id,
        "name": req.name,
        "description": req.description,
        "system_prompt": req.system_prompt,
        "created_at": created_at.isoformat()
    }

@router.post("/api/work", response_model=WorkResponse)
async def submit_work(req: WorkRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """
    Enqueue durable work. A WorkQueueWorker claims QUEUED rows via
    FOR UPDATE SKIP LOCKED — no in-process BackgroundTasks.
    """
    tenant_id = user.get("tenant_id", "default-tenant")
    task_id = str(uuid.uuid4())
    
    if not db_client.pool:
        await db_client.connect()
        
    async with db_client.pool.acquire() as conn:
        agent_prompt = await conn.fetchval(
            "SELECT system_prompt FROM agents WHERE id = $1 AND tenant_id = $2",
            req.agent_id,
            tenant_id,
        )
        if not agent_prompt:
            raise HTTPException(status_code=404, detail="Agent not found")

        if req.document_id:
            doc_ok = await conn.fetchval(
                "SELECT 1 FROM document_jobs WHERE document_id = $1 AND tenant_id = $2",
                req.document_id,
                tenant_id,
            )
            if not doc_ok:
                raise HTTPException(status_code=404, detail="Document not found for tenant")
            
        await conn.execute(
            """
            INSERT INTO agent_tasks (id, tenant_id, agent_id, document_id, status, prompt)
            VALUES ($1, $2, $3, $4, 'QUEUED', $5)
            """,
            task_id,
            tenant_id,
            req.agent_id,
            req.document_id,
            req.prompt,
        )
    
    return {"task_id": task_id, "status": "QUEUED"}

@router.get("/api/work")
async def list_work(user: Dict[str, Any] = Depends(get_current_user)):
    tenant_id = user.get("tenant_id", "default-tenant")
    if not db_client.pool:
        await db_client.connect()
        
    query = """
        SELECT t.id, t.status, t.result, t.updated_at, a.name as agent_name 
        FROM agent_tasks t
        JOIN agents a ON t.agent_id = a.id
        WHERE t.tenant_id = $1
        ORDER BY t.updated_at DESC
        LIMIT 50
    """
    async with db_client.pool.acquire() as conn:
        rows = await conn.fetch(query, tenant_id)
        
    return [
        {
            "id": r["id"],
            "name": r["agent_name"],
            "status": r["status"],
            "result": r["result"] if r["result"] else "-",
            "time": r["updated_at"].isoformat()
        }
        for r in rows
    ]
