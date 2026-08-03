"""Cube.js semantic layer query execution engine and tools."""
from __future__ import annotations

import json
from typing import Any, Dict
import httpx
import sqlglot
import sqlglot.expressions as exp
import structlog
from langchain_core.tools import tool

from tools.cube_mcp import CubeMCPClient

logger = structlog.get_logger(__name__)


def inject_tenant_id_sql(sql: str, tenant_id: str) -> str:
    """Uses AST parsing to securely inject WHERE tenant_id = '...' into all select nodes."""
    try:
        parsed = sqlglot.parse_one(sql)
        condition = f"tenant_id = '{tenant_id}'"
        for select in parsed.find_all(exp.Select):
            select.where(condition, copy=False)
        return parsed.sql()
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


class CubeQueryEngine:
    """Query engine for fetching Cube schemas and executing ANSI SQL queries."""

    def __init__(self, client: CubeMCPClient | None = None) -> None:
        self.client = client or CubeMCPClient()

    def fetch_schema(self) -> str:
        """Fetch the full semantic layer schema from Cube.js."""
        endpoint = self.client.endpoint.rstrip("/")
        if endpoint.endswith("/sql"):
            endpoint = endpoint[:-4]
        if not endpoint.endswith("/meta"):
            meta_url = f"{endpoint}/meta"
        else:
            meta_url = endpoint

        headers = {"Content-Type": "application/json"}
        if self.client.token:
            headers["Authorization"] = f"Bearer {self.client.token}"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(meta_url, headers=headers)
                if response.status_code == 200:
                    meta = response.json().get("meta", {})
                    schema_str = "Cube.js Semantic Schema:\n"
                    cubes = meta.get("cubes", [])
                    for c in cubes:
                        cube_name = c.get("name")
                        cube_type = c.get("type", "cube")
                        schema_str += f"- Cube/View: {cube_name} ({cube_type})\n"
                        for dim in c.get("dimensions", []):
                            schema_str += f"  - Dimension: {dim.get('name')} ({dim.get('type')})\n"
                        for meas in c.get("measures", []):
                            schema_str += f"  - Measure: {meas.get('name')} ({meas.get('type')})\n"
                    return schema_str
                return "Cube API returned error: " + response.text
        except Exception as e:
            logger.error("Failed to fetch cube schema", error=str(e))
            return "Failed to fetch schema due to network error."

    def execute_sql(self, query: str, tenant_id: str) -> str:
        """Execute tenant-scoped SQL query against Cube.js semantic layer."""
        secure_query = inject_tenant_id_sql(query, tenant_id)
        logger.info("Executing secure SQL", secure_query=secure_query)

        result = self.client.execute_sql(secure_query)
        if "error" in result:
            return f"SQL Error: {result['error']}"

        data = result.get("data", [])
        return json.dumps(data, indent=2)


cube_query_engine = CubeQueryEngine()
cube_client = cube_query_engine.client


@tool
def fetch_cube_schema() -> str:
    """
    Fetches the full semantic layer schema from Cube.js.
    Use this tool before writing SQL to understand what tables, dimensions, and measures are available.
    """
    return cube_query_engine.fetch_schema()


@tool
def execute_cube_sql(query: str, tenant_id: str) -> str:
    """
    Executes a SQL query against the Cube.js semantic layer.
    You MUST provide valid ANSI SQL. 
    The tenant_id will be automatically injected for security, do not include it yourself.
    """
    return cube_query_engine.execute_sql(query, tenant_id)
