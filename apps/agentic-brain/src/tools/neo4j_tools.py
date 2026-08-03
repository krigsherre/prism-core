import json
import structlog
from langchain_core.tools import tool
from core.neo4j_client import neo4j_client
from tools.cypher_security import inject_tenant_id_cypher

logger = structlog.get_logger(__name__)

@tool
async def fetch_neo4j_schema() -> str:
    """
    Fetches the schema (Nodes and Relationships) of the Knowledge Graph.
    Use this to understand what entities and edges exist before writing Cypher queries.
    """
    schema = await neo4j_client.get_schema()
    return schema

@tool
async def execute_cypher(query: str, tenant_id: str) -> str:
    """
    Executes a Cypher read query against the Neo4j Knowledge Graph.
    The tenant_id will be automatically injected into your MATCH clauses for security.
    """
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
        results = await neo4j_client.execute_read(secure_query)
        if not results:
            return "No results found."
        return json.dumps(results[:50], indent=2, default=str)
    except Exception as e:
        logger.error("Cypher execution failed", error=str(e))
        return f"Cypher Error: {str(e)}"
