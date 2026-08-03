"""Neo4j Knowledge Graph query execution engine and tools."""
from __future__ import annotations

import json
from typing import Any, Dict, List
import structlog
from langchain_core.tools import tool

from core.neo4j_client import neo4j_client
from tools.cypher_security import inject_tenant_id_cypher

logger = structlog.get_logger(__name__)


class Neo4jGraphEngine:
    """Engine encapsulating Cypher schema inspection and tenant-secured query execution."""

    def __init__(self, client: Any = neo4j_client) -> None:
        self.client = client

    async def get_schema(self) -> str:
        """Fetch the Cypher schema for graph entities and relationships."""
        return await self.client.get_schema()

    async def execute_cypher(self, query: str, tenant_id: str) -> str:
        """Sanitize and execute a Cypher read query with tenant-id injection."""
        if isinstance(query, str) and query.strip().startswith("{"):
            try:
                parsed = json.loads(query)
                if isinstance(parsed, dict) and "cypher" in parsed:
                    query = parsed["cypher"]
            except Exception:
                pass

        secure_query = inject_tenant_id_cypher(query, tenant_id)
        logger.info("Executing secure Cypher", secure_query=secure_query)

        try:
            results = await self.client.execute_read(secure_query)
            if not results:
                return "No results found."
            return json.dumps(results[:50], indent=2, default=str)
        except Exception as e:
            logger.error("Cypher execution failed", error=str(e))
            return f"Cypher Error: {str(e)}"


neo4j_engine = Neo4jGraphEngine()


@tool
async def fetch_neo4j_schema() -> str:
    """
    Fetches the schema (Nodes and Relationships) of the Knowledge Graph.
    Use this to understand what entities and edges exist before writing Cypher queries.
    """
    return await neo4j_engine.get_schema()


@tool
async def execute_cypher(query: str, tenant_id: str) -> str:
    """
    Executes a Cypher read query against the Neo4j Knowledge Graph.
    The tenant_id will be automatically injected into your MATCH clauses for security.
    """
    return await neo4j_engine.execute_cypher(query, tenant_id)
