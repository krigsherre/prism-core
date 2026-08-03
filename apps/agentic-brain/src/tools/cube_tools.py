import json
import structlog
import sqlglot
import sqlglot.expressions as exp
from langchain_core.tools import tool
from typing import Dict, Any
from tools.cube_mcp import CubeMCPClient

logger = structlog.get_logger(__name__)
cube_client = CubeMCPClient()

@tool
def fetch_cube_schema() -> str:
    """
    Fetches the full semantic layer schema from Cube.js.
    Use this tool before writing SQL to understand what tables, dimensions, and measures are available.
    """
    import httpx
    url = f"{cube_client.endpoint.replace('/sql', '/meta')}"
    headers = {"Content-Type": "application/json"}
    if cube_client.token:
        headers["Authorization"] = f"Bearer {cube_client.token}"
        
    try:
        with httpx.Client(timeout=1.0) as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                meta = response.json().get("meta", {})
                schema_str = "Cube.js Semantic Schema:\n"
                cubes = meta.get("cubes", [])
                for c in cubes:
                    if c.get("type") == "view":
                        schema_str += f"- View: {c.get('name')}\n"
                        for dim in c.get("dimensions", []):
                            schema_str += f"  - Dimension: {dim.get('name')} ({dim.get('type')})\n"
                        for meas in c.get("measures", []):
                            schema_str += f"  - Measure: {meas.get('name')} ({meas.get('type')})\n"
                return schema_str
            return "Cube API returned error: " + response.text
    except Exception as e:
        logger.error("Failed to fetch cube schema", error=str(e))
        return "Failed to fetch schema due to network error."

def inject_tenant_id_sql(sql: str, tenant_id: str) -> str:
    """Uses AST parsing to securely inject WHERE tenant_id = '...'."""
    try:
        parsed = sqlglot.parse_one(sql)
        condition = f"tenant_id = '{tenant_id}'"
        secure_sql = parsed.where(condition).sql()
        return secure_sql
    except Exception as e:
        logger.error("AST Parsing failed", sql=sql, error=str(e))
        if "WHERE" in sql.upper():
            return sql.replace("WHERE", f"WHERE tenant_id = '{tenant_id}' AND ", 1)
        else:
            parts = sql.split("FROM", 1)
            if len(parts) == 2:
                table_and_rest = parts[1].split(" ", 1)
                if len(table_and_rest) == 2:
                    return f"{parts[0]}FROM {table_and_rest[0]} WHERE tenant_id = '{tenant_id}' {table_and_rest[1]}"
        return sql

@tool
def execute_cube_sql(query: str, tenant_id: str) -> str:
    """
    Executes a SQL query against the Cube.js semantic layer.
    You MUST provide valid ANSI SQL. 
    The tenant_id will be automatically injected for security, do not include it yourself.
    """
    secure_query = inject_tenant_id_sql(query, tenant_id)
    logger.info("Executing secure SQL", secure_query=secure_query)
    
    result = cube_client.execute_sql(secure_query)
    
    if "error" in result:
        return f"SQL Error: {result['error']}"
        
    data = result.get("data", [])
    return json.dumps(data, indent=2)
