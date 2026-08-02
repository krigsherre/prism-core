import structlog
from neo4j import AsyncGraphDatabase
from core.config import settings

logger = structlog.get_logger(__name__)

class AsyncNeo4jClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AsyncNeo4jClient, cls).__new__(cls)
            cls._instance.driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
        return cls._instance

    async def execute_read(self, query: str, parameters: dict = None):
        """Execute a Cypher read query."""
        async with self.driver.session() as session:
            try:
                result = await session.run(query, parameters or {})
                records = await result.data()
                return records
            except Exception as e:
                logger.error("Neo4j read query failed", query=query, error=str(e))
                raise

    async def execute_write(self, query: str, parameters: dict = None):
        """Execute a Cypher write query."""
        async with self.driver.session() as session:
            try:
                result = await session.run(query, parameters or {})
                records = await result.data()
                return records
            except Exception as e:
                logger.error("Neo4j write query failed", query=query, error=str(e))
                raise

    async def get_schema(self) -> str:
        """Dynamically fetch the schema of the graph database for LLM context."""
        query = "CALL db.schema.visualization()"
        try:
            records = await self.execute_read(query)
            if not records:
                return "No graph schema found."
                
            nodes = records[0].get("nodes", [])
            relationships = records[0].get("relationships", [])
            
            node_labels = [n.get("name") for n in nodes if hasattr(n, "get")]
            rel_types = [r[1] for r in relationships if isinstance(r, tuple) and len(r) > 1]
            
            schema = "Graph Ontology:\n"
            schema += f"Nodes: {', '.join(str(n) for n in node_labels)}\n"
            schema += f"Relationships: {', '.join(str(r) for r in rel_types)}\n"
            return schema
        except Exception as e:
            logger.warning("Failed to fetch graph schema", error=str(e))
            return "Graph schema unavailable."

    async def close(self):
        if self.driver:
            await self.driver.close()

neo4j_client = AsyncNeo4jClient()
