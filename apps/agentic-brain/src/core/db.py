import structlog
import asyncpg
import json
from core.config import settings
from .broadcaster import status_broadcaster

logger = structlog.get_logger(__name__)

class AsyncPostgresClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AsyncPostgresClient, cls).__new__(cls)
            cls._instance.pool = None
        return cls._instance

    async def connect(self):
        if not self.pool:
            try:
                self.pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=1,
                    max_size=settings.db_pool_size
                )
                
                self.listener_conn = await self.pool.acquire()
                
                def handle_notification(connection, pid, channel, payload):
                    import asyncio
                    asyncio.create_task(status_broadcaster.broadcast(payload))
                    
                await self.listener_conn.add_listener('document_status_updates', handle_notification)
                
                logger.info("Connected to Postgres via asyncpg pool and listening for document_status_updates")
            except Exception as e:
                logger.error("Failed to connect to Postgres", error=str(e))
                raise

    async def fetch_jsonb(self, document_id: str) -> dict:
        """Fetch raw JSONB extracted data from Postgres."""
        if not self.pool: await self.connect()
        query = """
            SELECT strict_columns, unmapped_jsonb 
            FROM extracted_tables 
            WHERE document_id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, document_id)
            if row:
                return {
                    "strict_columns": dict(row['strict_columns']) if row['strict_columns'] else {},
                    "unmapped_jsonb": dict(row['unmapped_jsonb']) if row['unmapped_jsonb'] else {}
                }
            return {}

    async def patch_jsonb(self, document_id: str, updates: dict) -> bool:
        """Patch JSONB using simple dict merge in Python and overwrite (or jsonb_set)."""
        if not self.pool: await self.connect()
        
        current = await self.fetch_jsonb(document_id)
        if not current:
            return False
            
        strict = current.get("strict_columns", {})
        strict.update(updates)
        
        query = """
            UPDATE extracted_tables 
            SET strict_columns = $1, 
                mapping_status = 'MAPPED',
                updated_at = NOW()
            WHERE document_id = $2
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, json.dumps(strict), document_id)
            return True

    async def close(self):
        if hasattr(self, 'listener_conn') and self.listener_conn:
            await self.pool.release(self.listener_conn)
        if self.pool:
            await self.pool.close()

    def acquire(self):
        if not self.pool:
            raise RuntimeError("Database pool is not connected")
        return self.pool.acquire()

db_client = AsyncPostgresClient()
