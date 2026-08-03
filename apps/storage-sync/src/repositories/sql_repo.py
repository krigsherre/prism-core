from typing import Any, Dict, List, Optional
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tenacity import retry, stop_after_attempt, wait_exponential

from db.models import ExtractedTable
from db.postgres import AsyncSessionLocal
from repositories.interfaces import ISQLRepository


class SQLRepository(ISQLRepository):
    """
    SQL persistence repository handling extracted table operations.
    Supports inserting aligned rows, updating existing rows, and querying unmapped rows for auto-promotion.
    """

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or AsyncSessionLocal

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def insert_aligned_rows(
        self,
        tenant_id: str,
        document_id: str,
        node_id: str,
        target_table: str,
        mapping_status: str,
        strict_columns_list: List[Dict[str, Any]],
        unmapped_jsonb_list: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        source_page: Optional[int] = None,
        source_bbox: Optional[List[float]] = None,
    ) -> None:
        """Insert or update extracted tabular data rows using PostgreSQL upsert ON CONFLICT DO UPDATE."""
        async with self.session_factory() as session:
            async with session.begin():
                for row_idx, (strict_cols, unmapped) in enumerate(zip(strict_columns_list, unmapped_jsonb_list)):
                    stmt = pg_insert(ExtractedTable).values(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        node_id=node_id,
                        row_index=row_idx,
                        user_id=user_id,
                        source_page=source_page,
                        source_bbox=source_bbox,
                        target_table=target_table,
                        mapping_status=mapping_status,
                        strict_columns=strict_cols,
                        unmapped_jsonb=unmapped,
                    )

                    stmt = stmt.on_conflict_do_update(
                        index_elements=["document_id", "node_id", "row_index"],
                        set_=dict(
                            target_table=stmt.excluded.target_table,
                            mapping_status=stmt.excluded.mapping_status,
                            strict_columns=stmt.excluded.strict_columns,
                            unmapped_jsonb=stmt.excluded.unmapped_jsonb,
                            user_id=stmt.excluded.user_id,
                            source_page=stmt.excluded.source_page,
                            source_bbox=stmt.excluded.source_bbox,
                        ),
                    )
                    await session.execute(stmt)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def update_aligned_table(
        self,
        row_id: int,
        mapping_status: str,
        strict_columns: Dict[str, Any],
        unmapped_jsonb: Dict[str, Any],
        target_table: str,
        user_id: Optional[str] = None,
        source_page: Optional[int] = None,
        source_bbox: Optional[List[float]] = None,
    ) -> None:
        """Update an existing aligned table row by primary ID."""
        async with self.session_factory() as session:
            async with session.begin():
                values: Dict[str, Any] = {
                    "mapping_status": mapping_status,
                    "strict_columns": strict_columns,
                    "unmapped_jsonb": unmapped_jsonb,
                    "target_table": target_table,
                }
                if user_id is not None:
                    values["user_id"] = user_id
                if source_page is not None:
                    values["source_page"] = source_page
                if source_bbox is not None:
                    values["source_bbox"] = source_bbox

                stmt = update(ExtractedTable).where(ExtractedTable.id == row_id).values(**values)
                await session.execute(stmt)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def get_unmapped_rows_by_table(self, target_table: str) -> List[Dict[str, Any]]:
        """Fetch all rows with NEEDS_REVIEW mapping status for target_table or UNKNOWN_TABLE."""
        async with self.session_factory() as session:
            stmt = select(ExtractedTable).where(
                ExtractedTable.target_table.in_([target_table, "UNKNOWN_TABLE"]),
                ExtractedTable.mapping_status == "NEEDS_REVIEW",
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": row.id,
                    "tenant_id": row.tenant_id,
                    "document_id": row.document_id,
                    "target_table": row.target_table,
                    "strict_columns": row.strict_columns,
                    "unmapped_jsonb": row.unmapped_jsonb,
                }
                for row in rows
            ]
