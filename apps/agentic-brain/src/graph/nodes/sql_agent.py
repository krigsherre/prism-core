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


class SingleSQLQuery(BaseModel):
    """Spec for a single exact view lookup or Cube query."""
    mode: Literal["exact", "cube"] = Field(
        description="'exact' for row values from Postgres views; 'cube' for aggregations via Cube.js"
    )
    view_name: Optional[str] = Field(
        default=None,
        description="For mode=exact: view_* name from list_exact_views",
    )
    filters_json: str = Field(
        default="{}",
        description='For mode=exact: JSON object of equality filters, e.g. {"sys_document_id":"..."}',
    )
    sql: Optional[str] = Field(
        default=None,
        description="For mode=cube: valid ANSI SQL against Cube.js",
    )
    purpose: str = Field(default="", description="e.g. Income Statement metrics, Balance Sheet liquidity")


class MultiSQLPlanOutput(BaseModel):
    """Plan containing one or more parallel queries to gather complete financial data."""
    queries: list[SingleSQLQuery] = Field(
        description="List of 1 to 4 queries to execute in parallel across financial tables"
    )
    reasoning: str = Field(default="", description="Brief reason for selected queries")


class SQLPlanOutput(BaseModel):
    """Legacy single plan fallback."""
    mode: Literal["exact", "cube"] = Field(default="exact")
    view_name: Optional[str] = Field(default=None)
    filters_json: str = Field(default="{}")
    sql: Optional[str] = Field(default=None)
    reasoning: str = Field(default="")


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

    table_map = {}
    if db_client.pool:
        try:
            async with db_client.pool.acquire() as conn:
                doc_tables = await conn.fetch(
                    "SELECT document_id, ARRAY_AGG(DISTINCT target_table) as tables FROM extracted_tables WHERE tenant_id = $1 GROUP BY document_id",
                    tenant_id
                )
                table_map = {r["document_id"]: [t for t in (r["tables"] or []) if t] for r in doc_tables}
        except Exception as e:
            logger.warning("Could not fetch document table mapping for catalog", error=str(e))

    doc_catalog_lines = []
    for d in docs:
        doc_id = d["document_id"]
        t_list = table_map.get(doc_id) or ["standardized_balance_sheet"]
        doc_catalog_lines.append(
            f"- [ID: {doc_id}] File: {d['filename']} | Company: {d.get('company_name')} ({d.get('ticker')}) | Period: {d.get('fiscal_period')} | Available Tables: {', '.join(t_list)}"
        )
    doc_catalog = "\n".join(doc_catalog_lines)

    llm = LLMFactory.get_structured_llm(MultiSQLPlanOutput, ModelTier.FRONTIER)
    
    cube_info = f"\nAVAILABLE CUBE SEMANTIC SCHEMA (mode=cube):\n{cube_schema}\n" if has_cube else "\nCUBE SCHEMA AVAILABLE: False\n"

    system_prompt = f"""You are an expert SQL planner for Agentic Brain.
Your goal is to formulate a plan containing 1 to 4 parallel queries to retrieve complete financial data from the database.

AVAILABLE POSTGRES VIEWS (mode=exact):
{postgres_views}

{cube_info}

AVAILABLE DOCUMENTS IN KNOWLEDGE BASE:
{doc_catalog}
Use these IDs to filter `sys_document_id` if the user asks for a specific company, ticker, or document.

For ratio calculations, aggregations, or financial totals, use mode=cube if available.
For exact table line items, use mode=exact against view_* names.

For complex questions, return MULTIPLE queries in `queries` (e.g. one for Income Statement, one for Balance Sheet) to gather complete financial context.
"""
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt, additional_kwargs={"cache_control": {"type": "ephemeral"}}),
            HumanMessage(content=user_msg)
        ])
        
        queries_list = []
        if hasattr(response, "queries") and response.queries:
            for q in response.queries:
                queries_list.append({
                    "mode": q.mode,
                    "view_name": q.view_name,
                    "filters_json": q.filters_json or "{}",
                    "sql": q.sql or "",
                    "purpose": q.purpose or ""
                })
        else:
            queries_list = [{
                "mode": getattr(response, "mode", "exact"),
                "view_name": getattr(response, "view_name", "extracted_tables"),
                "filters_json": getattr(response, "filters_json", "{}"),
                "sql": getattr(response, "sql", ""),
                "purpose": "Primary financial metrics"
            }]
            
        plan = {
            "queries": queries_list,
            "reasoning": getattr(response, "reasoning", "LLM generation successful")
        }
    except Exception as e:
        logger.error("SQL Planner LLM failed", error=str(e))
        plan = {
            "queries": [{
                "mode": "exact",
                "view_name": "extracted_tables",
                "filters_json": "{}",
                "sql": "",
                "purpose": "Fallback query"
            }],
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
        return {"mode": "exact", "queries": [{"mode": "exact", "view_name": "extracted_tables", "sql": ""}]}
    try:
        parsed = json.loads(sql_query)
        if isinstance(parsed, dict):
            if "queries" in parsed and isinstance(parsed["queries"], list):
                out = dict(parsed)
                if parsed["queries"] and isinstance(parsed["queries"][0], dict):
                    out.setdefault("mode", parsed["queries"][0].get("mode", "exact"))
                    out.setdefault("view_name", parsed["queries"][0].get("view_name", ""))
                return out
            if "mode" in parsed:
                return {"mode": parsed["mode"], "view_name": parsed.get("view_name", ""), "queries": [parsed]}
    except (json.JSONDecodeError, TypeError):
        pass
    return {"mode": "cube", "sql": sql_query, "queries": [{"mode": "cube", "sql": sql_query}]}


def _build_references_from_exact(result_json: str) -> list:
    refs = []
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return refs
    
    rows = data.get("rows") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        doc_id = row.get("sys_document_id") or row.get("document_id")
        raw_page = row.get("source_page") or row.get("page_number") or row.get("sys_page_number") or row.get("page")
        try:
            page = int(raw_page) if raw_page is not None else 1
        except (ValueError, TypeError):
            page = 1
        node_id = row.get("sys_node_id") or row.get("node_id")
        filename = row.get("sys_filename") or row.get("filename") or "Document"
        company = row.get("sys_company_name") or row.get("company_name") or ""
        if not doc_id:
            continue
            
        key = (doc_id, page)
        if key in seen:
            continue
        seen.add(key)

        refs.append(
            {
                "doc_id": doc_id,
                "document_id": doc_id,
                "filename": filename,
                "company_name": company,
                "node_id": node_id,
                "source_page": page,
                "page": page,
                "source": "postgres_exact",
                "view": data.get("view") if isinstance(data, dict) else "",
            }
        )
    return refs[:20]


def execute_sql_node(state: InteractionState) -> dict:
    """
    Executes the planned SQL queries (exact Postgres view or Cube aggregation).
    Supports parallel batch execution of multiple queries via multi_query plan.
    """
    plan = _parse_plan(state.get("sql_query", ""))
    tenant_id = state.get("tenant_id", "default-tenant")
    document_id = state.get("document_id") or ""
    queries = plan.get("queries") or [{"mode": "exact", "view_name": "extracted_tables"}]
    logger.info("Executing SQL plan", query_count=len(queries), plan=plan)

    combined_results = []
    all_references = []

    for q in queries:
        mode = q.get("mode", "exact")
        purpose = q.get("purpose", "")
        try:
            if mode == "exact":
                view_name = q.get("view_name") or "extracted_tables"
                filters_json = q.get("filters_json") or "{}"
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
                sql_to_run = q.get("sql") or ""
                result = execute_cube_sql.invoke({"query": sql_to_run, "tenant_id": tenant_id})
                if isinstance(result, str) and (
                    "Connection refused" in result
                    or "Network Error" in result
                    or "SQL Error" in result
                ):
                    logger.warning("Cube failed — falling back to exact extracted_tables", error=result)
                    result = query_exact_rows.invoke(
                        {
                            "view_name": q.get("view_name") or "extracted_tables",
                            "tenant_id": tenant_id,
                            "document_id": document_id,
                            "filters_json": q.get("filters_json") or "{}",
                            "limit": 100,
                        }
                    )

            if isinstance(result, str) and "SQL Error" in result:
                logger.warning("SQL Execution Failed for query", purpose=purpose, error=result)
                continue

            combined_results.append({
                "purpose": purpose,
                "view": q.get("view_name"),
                "result": result
            })
            all_references.extend(_build_references_from_exact(result))

        except Exception as e:
            logger.error("SQL Tool crashed for query", purpose=purpose, error=str(e))

    if not combined_results:
        return {
            "error_message": "All SQL queries failed to execute.",
            "retries": 1,
        }

    deduped_refs = []
    seen_keys = set()
    for ref in all_references:
        d_id = ref.get("doc_id") or ref.get("document_id") or ""
        r_pg = ref.get("source_page") or ref.get("page") or ref.get("page_number") or 1
        try:
            p_num = int(r_pg)
        except (ValueError, TypeError):
            p_num = 1
        ref_key = (d_id, p_num)
        if ref_key not in seen_keys:
            seen_keys.add(ref_key)
            deduped_refs.append(ref)

    return {
        "error_message": "",
        "sql_result": json.dumps(combined_results, indent=2, default=str),
        "references": deduped_refs[:20],
    }
