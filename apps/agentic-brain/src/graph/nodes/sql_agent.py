import json
import structlog
from typing import Literal, Optional
from pydantic import BaseModel, Field
from llm.factory import LLMFactory, ModelTier
from langchain_core.messages import SystemMessage, HumanMessage
from graph.state import InteractionState
from tools.cube_tools import fetch_cube_schema, execute_cube_sql
from tools.postgres_tools import list_exact_views, query_exact_rows

logger = structlog.get_logger(__name__)


class SQLPlanOutput(BaseModel):
    """Plan for either exact Postgres view lookup or Cube aggregation SQL."""

    mode: Literal["exact", "cube"] = Field(
        description=(
            "'exact' for row/cell-accurate values from Postgres views; "
            "'cube' for aggregations/rollups via Cube.js"
        )
    )
    view_name: Optional[str] = Field(
        default=None,
        description="For mode=exact: allowlisted view_* name from list_exact_views",
    )
    filters_json: str = Field(
        default="{}",
        description='For mode=exact: JSON object of equality filters, e.g. {"vendor_name":"Acme"}',
    )
    sql: Optional[str] = Field(
        default=None,
        description="For mode=cube: valid ANSI SQL against Cube.js. No markdown fences.",
    )
    reasoning: str = Field(default="", description="Brief reason for choosing exact vs cube")


async def generate_sql_node(state: InteractionState) -> dict:
    """
    Plans SQL access: exact Postgres views for precise data, Cube for aggregations.
    Uses Frontier LLM for high-accuracy SQL generation.
    """
    logger.info("Generating SQL plan", retries=state.get("retries", 0))

    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break

    cube_schema = fetch_cube_schema.invoke({})
    has_cube = _cube_schema_available(cube_schema)
    postgres_views = list_exact_views.invoke({})
    
    from core.db import db_client
    tenant_id = state.get("tenant_id", "default-tenant")
    docs = await db_client.fetch_tenant_documents(tenant_id)
    doc_catalog = "\n".join([
        f"- [ID: {d['document_id']}] File: {d['filename']} | Company: {d.get('company_name')} ({d.get('ticker')}) | Period: {d.get('fiscal_period')}"
        for d in docs
    ])

    llm = LLMFactory.get_structured_llm(SQLPlanOutput, ModelTier.FRONTIER)
    
    system_prompt = f"""You are an expert SQL planner for Agentic Brain.
Your goal is to formulate a plan to retrieve exact financial data from the database.

AVAILABLE POSTGRES VIEWS (mode=exact):
{postgres_views}

AVAILABLE DOCUMENTS IN KNOWLEDGE BASE:
{doc_catalog}
Use these IDs to filter `sys_document_id` if the user asks for a specific company, ticker, or document.

If the user wants aggregations, use mode=cube if available.
CUBE SCHEMA AVAILABLE: {has_cube}

You must return a valid SQLPlanOutput. For mode=exact, provide 'view_name' and 'filters_json' (e.g. {{"sys_document_id": "uuid-here"}}).
"""
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt, additional_kwargs={"cache_control": {"type": "ephemeral"}}),
            HumanMessage(content=user_msg)
        ])
        
        plan = {
            "mode": response.mode,
            "view_name": response.view_name,
            "filters_json": response.filters_json or "{}",
            "sql": response.sql or "",
            "reasoning": response.reasoning or "LLM generation successful"
        }
    except Exception as e:
        logger.error("SQL Planner LLM failed", error=str(e))
        plan = {
            "mode": "exact",
            "view_name": "extracted_tables",
            "filters_json": "{}",
            "sql": "",
            "reasoning": "Fallback due to LLM error",
        }

    return {"sql_query": json.dumps(plan)}


def _cube_schema_available(cube_schema: str) -> bool:
    text = (cube_schema or "").lower()
    if not text.strip():
        return False
    bad = ("failed to fetch", "network error", "connection refused", "cube api returned error")
    return not any(b in text for b in bad)


def _is_aggregation_intent(user_msg: str) -> bool:
    import re
    text = (user_msg or "").lower()
    patterns = (
        r"\btotal\b", r"\bsum\b", r"\baverage\b", r"\bavg\b", r"\bcount\b",
        r"\bhow many\b", r"\baggregate\b", r"\bacross all\b", r"\boverall\b",
        r"\brollup\b", r"\bmean\b", r"\bmedian\b",
    )
    return any(re.search(p, text) for p in patterns)


def _parse_plan(sql_query: str) -> dict:
    if not sql_query:
        return {"mode": "exact", "view_name": "extracted_tables", "sql": ""}
    try:
        parsed = json.loads(sql_query)
        if isinstance(parsed, dict) and "mode" in parsed:
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return {"mode": "cube", "sql": sql_query}


def _build_references_from_exact(result_json: str) -> list:
    refs = []
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return refs
    for row in data.get("rows") or []:
        doc_id = row.get("sys_document_id")
        page = row.get("source_page")
        node_id = row.get("sys_node_id")
        if not doc_id:
            continue
        refs.append(
            {
                "document_id": doc_id,
                "node_id": node_id,
                "page": page,
                "source": "postgres_exact",
                "view": data.get("view"),
            }
        )
    return refs[:20]


def execute_sql_node(state: InteractionState) -> dict:
    """
    Executes the planned SQL (exact Postgres view or Cube aggregation).
    On failure, increments retries for Reflexion.
    """
    plan = _parse_plan(state.get("sql_query", ""))
    tenant_id = state.get("tenant_id", "default-tenant")
    document_id = state.get("document_id") or ""
    mode = plan.get("mode", "exact")
    logger.info("Executing SQL plan", mode=mode, plan=plan)

    try:
        if mode == "exact":
            view_name = plan.get("view_name") or "extracted_tables"
            filters_json = plan.get("filters_json") or "{}"
            result = query_exact_rows.invoke(
                {
                    "view_name": view_name,
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "filters_json": filters_json,
                    "limit": 100,
                }
            )
        else:
            sql_to_run = plan.get("sql") or ""
            result = execute_cube_sql.invoke({"query": sql_to_run, "tenant_id": tenant_id})
            if isinstance(result, str) and (
                "Connection refused" in result
                or "Network Error" in result
                or "SQL Error" in result
            ):
                logger.warning("Cube failed — falling back to exact extracted_tables", error=result)
                result = query_exact_rows.invoke(
                    {
                        "view_name": plan.get("view_name") or "extracted_tables",
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "filters_json": plan.get("filters_json") or "{}",
                        "limit": 100,
                    }
                )
                mode = "exact"

        if isinstance(result, str) and "SQL Error" in result:
            logger.warning("SQL Execution Failed", error=result, mode=mode)
            return {
                "error_message": result,
                "retries": 1,
            }

        references = _build_references_from_exact(result) if mode == "exact" else []

        return {
            "error_message": "",
            "sql_result": result,
            "references": references,
        }

    except Exception as e:
        logger.error("SQL Tool crashed", error=str(e))
        return {
            "error_message": str(e),
            "retries": 1,
        }
