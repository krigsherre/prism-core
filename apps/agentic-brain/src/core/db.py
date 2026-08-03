"""PostgreSQL Database Client & Connection Manager."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
import asyncpg
import structlog

from core.config import settings
from .broadcaster import status_broadcaster
from .repositories import (
    ChatAuditRepository,
    DocumentRepository,
    ExtractedTableRepository,
)

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """
    Singleton database connection pool manager and repository provider.
    """
    _instance: Optional[DatabaseManager] = None

    def __new__(cls) -> DatabaseManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.pool = None
            cls._instance.listener_conn = None
            cls._instance._lock = None
            cls._instance._init_repositories()
        return cls._instance

    def _init_repositories(self) -> None:
        self._doc_repo = DocumentRepository(self)
        self._extracted_table_repo = ExtractedTableRepository(self)
        self._audit_repo = ChatAuditRepository(self)

    @property
    def documents(self) -> DocumentRepository:
        return self._doc_repo

    @property
    def extracted_tables(self) -> ExtractedTableRepository:
        return self._extracted_table_repo

    @property
    def chat_audits(self) -> ChatAuditRepository:
        return self._audit_repo

    async def connect(self) -> None:
        """Establish pool connection and LISTEN connection for status updates."""
        if not self.pool:
            if getattr(self, "_lock", None) is None:
                self._lock = asyncio.Lock()
            async with self._lock:
                if not self.pool:
                    try:
                        self.pool = await asyncpg.create_pool(
                            settings.database_url,
                            min_size=1,
                            max_size=settings.db_pool_size,
                        )

                        self.listener_conn = await asyncpg.connect(settings.database_url)

                        def handle_notification(connection, pid, channel, payload):
                            asyncio.create_task(status_broadcaster.broadcast(payload))

                        await self.listener_conn.add_listener(
                            "document_status_updates", handle_notification
                        )

                        logger.info(
                            "Connected to Postgres via asyncpg pool and listening for document_status_updates"
                        )
                    except Exception as e:
                        logger.error("Failed to connect to Postgres", error=str(e))
                        raise

    async def close(self) -> None:
        """Gracefully close listener connection and connection pool."""
        if self.listener_conn:
            try:
                await self.listener_conn.close()
            except Exception:
                pass
            self.listener_conn = None

        if self.pool:
            await self.pool.close()
            self.pool = None

    def acquire(self):
        """Acquire a connection context manager from pool."""
        if not self.pool:
            raise RuntimeError("Database pool is not connected")
        return self.pool.acquire()

    # Backwards compatible repository method delegates
    async def fetch_jsonb(self, document_id: str) -> Dict[str, Any]:
        return await self._extracted_table_repo.fetch_jsonb(document_id)

    async def patch_jsonb(self, document_id: str, updates: Dict[str, Any]) -> bool:
        return await self._extracted_table_repo.patch_jsonb(document_id, updates)

    async def insert_chat_audit_log(self, audit_data: Dict[str, Any]) -> None:
        await self._audit_repo.insert_chat_audit_log(audit_data)

    async def fetch_tenant_documents(self, tenant_id: str) -> List[Dict[str, Any]]:
        return await self._doc_repo.fetch_tenant_documents(tenant_id)


# Legacy Class Alias for Backwards Compatibility
AsyncPostgresClient = DatabaseManager

db_client = DatabaseManager()
