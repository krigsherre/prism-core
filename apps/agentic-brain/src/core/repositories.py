"""Domain repositories for clean data access across PostgreSQL tables."""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional
import asyncpg
import structlog

logger = structlog.get_logger(__name__)


class BaseRepository:
    """Base repository encapsulating connection pool access."""

    def __init__(self, pool_provider: Any) -> None:
        self._pool_provider = pool_provider

    @property
    def pool(self) -> asyncpg.Pool | None:
        return getattr(self._pool_provider, "pool", None)

    async def _ensure_pool(self) -> asyncpg.Pool:
        if not self.pool:
            await self._pool_provider.connect()
        if not self.pool:
            raise RuntimeError("Database pool unavailable")
        return self.pool


class DocumentRepository(BaseRepository):
    """Repository for managing document jobs and tenant document metadata."""

    async def fetch_tenant_documents(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Fetch available documents and their metadata for a given tenant."""
        pool = await self._ensure_pool()
        query = """
            SELECT 
                COALESCE(dj.document_id, et.document_id) AS document_id,
                COALESCE(dj.filename, 'Document ' || COALESCE(dj.document_id, et.document_id)) AS filename,
                COALESCE(dj.company_name, et.strict_columns->>'company_name', et.unmapped_jsonb->>'company_name', et.unmapped_jsonb->>'Company Name', 'Apple Inc.') AS company_name,
                COALESCE(dj.ticker, et.strict_columns->>'ticker', et.unmapped_jsonb->>'ticker', et.unmapped_jsonb->>'Ticker', 'AAPL') AS ticker,
                COALESCE(dj.fiscal_period, et.strict_columns->>'fiscal_period', et.unmapped_jsonb->>'fiscal_period', et.unmapped_jsonb->>'Period', 'FY2025') AS fiscal_period
            FROM document_jobs dj
            FULL OUTER JOIN (
                SELECT DISTINCT document_id, strict_columns, unmapped_jsonb, tenant_id
                FROM extracted_tables
                WHERE document_id IS NOT NULL AND document_id != ''
            ) et ON dj.document_id = et.document_id AND (dj.tenant_id = et.tenant_id OR dj.tenant_id IS NULL)
            WHERE dj.tenant_id = $1 OR et.tenant_id = $1 OR dj.tenant_id IS NULL OR $1 = 'default-tenant';
        """
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, tenant_id)
                docs = [dict(r) for r in rows if r.get("document_id")]
                if docs:
                    return docs
        except Exception as e:
            logger.warning("Failed to query joined document metadata", error=str(e))

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT document_id, filename, company_name, ticker, fiscal_period FROM document_jobs WHERE tenant_id = $1 OR $1 = 'default-tenant'",
                    tenant_id,
                )
                return [dict(r) for r in rows]
        except Exception:
            return []


class ExtractedTableRepository(BaseRepository):
    """Repository for fetching and updating extracted table JSONB records."""

    async def fetch_jsonb(self, document_id: str) -> Dict[str, Any]:
        """Fetch raw JSONB extracted data from Postgres."""
        pool = await self._ensure_pool()
        query = """
            SELECT strict_columns, unmapped_jsonb 
            FROM extracted_tables 
            WHERE document_id = $1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, document_id)
            if row:
                return {
                    "strict_columns": dict(row["strict_columns"]) if row["strict_columns"] else {},
                    "unmapped_jsonb": dict(row["unmapped_jsonb"]) if row["unmapped_jsonb"] else {},
                }
            return {}

    async def patch_jsonb(self, document_id: str, updates: Dict[str, Any]) -> bool:
        """Patch JSONB using dict merge and update extracted_tables status."""
        pool = await self._ensure_pool()
        current = await self.fetch_jsonb(document_id)
        if not current:
            return False

        strict = current.get("strict_columns", {})
        strict.update(updates)

        query = """
            UPDATE extracted_tables 
            SET strict_columns = $1::jsonb, 
                mapping_status = 'MAPPED',
                updated_at = NOW()
            WHERE document_id = $2
        """
        async with pool.acquire() as conn:
            await conn.execute(query, json.dumps(strict), document_id)
            return True


class ChatAuditRepository(BaseRepository):
    """Repository for inserting and managing chat audit logs."""

    async def insert_chat_audit_log(self, audit_data: Dict[str, Any]) -> str:
        """Insert a chat audit log record into Postgres."""
        pool = await self._ensure_pool()
        query = """
            INSERT INTO chat_audit_logs (
                id, tenant_id, thread_id, document_id, user_message, agent_response,
                sql_accessed, vector_accessed, graph_accessed, llm_traces,
                input_tokens, output_tokens
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
            )
        """
        log_id = str(uuid.uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                query,
                log_id,
                audit_data.get("tenant_id", "default-tenant"),
                audit_data.get("thread_id", ""),
                audit_data.get("document_id", ""),
                audit_data.get("user_message", ""),
                audit_data.get("agent_response", ""),
                audit_data.get("sql_accessed", False),
                audit_data.get("vector_accessed", False),
                audit_data.get("graph_accessed", False),
                json.dumps(audit_data.get("llm_traces", [])) if audit_data.get("llm_traces") else None,
                audit_data.get("input_tokens", None),
                audit_data.get("output_tokens", None),
            )
            logger.info("Chat audit log inserted", log_id=log_id, thread_id=audit_data.get("thread_id"))
            return log_id
