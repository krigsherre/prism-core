from typing import Any, Dict, List, Optional, Protocol
from qdrant_client import models


class ISQLRepository(Protocol):
    """Abstract protocol for SQL database persistence."""

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
        ...

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
        ...

    async def get_unmapped_rows_by_table(self, target_table: str) -> List[Dict[str, Any]]:
        ...


class IQdrantRepository(Protocol):
    """Abstract protocol for Qdrant vector database persistence."""

    async def initialize_collection(self) -> None:
        ...

    async def upsert_vector(
        self, node_id: str, document_id: str, vector: List[float], payload: Dict[str, Any]
    ) -> None:
        ...

    async def upsert_batch(self, points: List[models.PointStruct]) -> None:
        ...

    async def delete_vector(self, node_id: str) -> None:
        ...
