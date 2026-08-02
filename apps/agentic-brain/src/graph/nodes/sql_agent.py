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


def generate_sql_node(state: InteractionState) -> dict:
    """
    Plans SQL access: exact Postgres views for precise data, Cube for aggregations.
    Applies the Reflexion pattern if an error_message exists.
    """
    logger.info("Generating SQL plan", retries=state.get("retries", 0))

    cube_schema = fetch_cube_schema.invoke({})
    exact_schema = list_exact_views.invoke({})
    document_id = state.get("document_id") or ""
    cube_available = _cube_schema_available(cube_schema)

    llm = LLMFactory.get_llm(tier=ModelTier.STANDARD)
    structured_llm = llm.with_structured_output(SQLPlanOutput)

    cube_block = (
        cube_schema
        if cube_available
        else "Cube.js is UNAVAILABLE (connection refused). Do NOT use mode='cube'."
    )

    system_prompt = f"""You are a master Data Engineer for a multi-tenant document platform.
Choose the right SQL backend and return a structured plan.

EXACT POSTGRES (preferred for exact numbers, row lookups, reconciliations, "what is the value of X"):
{exact_schema}

CUBE.JS SEMANTIC LAYER (only if available — aggregations/rollups):
{cube_block}

CRITICAL RULES:
1. DEFAULT to mode='exact'. Use view_name from the list (view_* or extracted_tables).
2. Use mode='cube' ONLY if Cube is available AND the user clearly asks for aggregations across many docs.
3. Do NOT include tenant_id filters — the system injects tenant isolation.
4. For exact mode, set view_name and optional filters_json equality filters.
5. Do NOT filter on mapping_status in filters_json — the exact query layer prefers MAPPED and falls back to NEEDS_REVIEW automatically.
6. For cube mode, set sql to raw ANSI SQL only (no markdown).
7. If you see an 'Execution Error' below, fix your plan based on that error — prefer switching to exact.
"""

    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break

    prompt_context = f"User Intent: {user_msg}\n"
    prompt_context += f"document_id in scope: {document_id or '(none — tenant-wide)'}\n"
    prompt_context += f"Cube available: {cube_available}\n"
    if document_id:
        prompt_context += (
            "IMPORTANT: document_id is set — prefer mode=exact unless this is clearly an aggregation.\n"
        )
    if not cube_available:
        prompt_context += "IMPORTANT: Cube is down — you MUST use mode=exact.\n"
    if state.get("error_message"):
        prompt_context += (
            f"\nPREVIOUS EXECUTION ERROR:\n{state['error_message']}\n\n"
            "Please fix your SQL plan. If Cube failed, switch to mode=exact."
        )

    response = structured_llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt_context),
        ]
    )

    mode = response.mode
    if not cube_available:
        mode = "exact"
    elif document_id and mode == "cube" and not _is_aggregation_intent(user_msg) and response.view_name:
        mode = "exact"
        logger.info("Overriding cube→exact for document-scoped query", view=response.view_name)

    view_name = response.view_name or ("extracted_tables" if mode == "exact" else None)
    plan = {
        "mode": mode,
        "view_name": view_name,
        "filters_json": response.filters_json or "{}",
        "sql": response.sql or "",
        "reasoning": response.reasoning,
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

        user_msg = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage):
                user_msg = msg.content
                break

        llm = LLMFactory.get_llm(tier=ModelTier.STANDARD)
        source_label = (
            "exact Postgres rows (authoritative extracted values)"
            if mode == "exact"
            else "Cube.js aggregation results"
        )
        system_prompt = f"""You are an expert Data Analyst.
Answer the user's question based ONLY on the following {source_label}.
For exact mode:
- Prefer rows with data_quality/trust_level "verified" (MAPPED) as ground truth.
- If data_quality is "provisional" (NEEDS_REVIEW fallback), still answer from those rows but clearly mark figures as provisional / pending review.
- Do not invent values for null/missing cells.
If row_count is 0, say you could not find matching extracted data (do not invent Apple/finance facts).
Do not mention the SQL query itself; answer clearly and concisely.
Cite document_id / page when present in the rows.

<data>
{result}
</data>
"""

        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        references = _build_references_from_exact(result) if mode == "exact" else []

        return {
            "error_message": "",
            "sql_result": response.content,
            "references": references,
        }

    except Exception as e:
        logger.error("SQL Tool crashed", error=str(e))
        return {
            "error_message": str(e),
            "retries": 1,
        }
