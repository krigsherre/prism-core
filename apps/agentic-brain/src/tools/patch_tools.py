import structlog
from langchain_core.tools import tool
from core.db import db_client
from core.neo4j_client import neo4j_client

logger = structlog.get_logger(__name__)

@tool
async def patch_postgres_json(document_id: str, field_name: str, correct_value: str) -> str:
    """
    Patches a specific field in the Postgres JSONB extracted_tables.
    Use this when a human provides feedback correcting a value that was extracted.
    """
    logger.info("Patching Postgres JSONB", document_id=document_id, field=field_name)
    success = await db_client.patch_jsonb(document_id, {field_name: correct_value})
    if success:
        return f"Successfully updated {field_name} in Postgres for document {document_id}."
    return f"Failed to update {field_name}. Document not found."

@tool
async def correct_neo4j_edge(subject_name: str, original_predicate: str, new_predicate: str, object_name: str) -> str:
    """
    Corrects a relationship (edge) in the Neo4j Knowledge Graph.
    Deletes the original relationship and creates the new one.
    """
    logger.info("Patching Neo4j Edge", subject=subject_name, old_rel=original_predicate, new_rel=new_predicate)
    
    query = f"""
    MATCH (s)-[r:{original_predicate}]->(o)
    WHERE s.name = $subject_name AND o.name = $object_name
    DELETE r
    CREATE (s)-[:{new_predicate}]->(o)
    """
    
    try:
        await neo4j_client.execute_write(query, {"subject_name": subject_name, "object_name": object_name})
        return f"Successfully changed relationship {original_predicate} to {new_predicate}."
    except Exception as e:
        logger.error("Failed to patch Neo4j edge", error=str(e))
        return f"Failed to correct edge: {str(e)}"
