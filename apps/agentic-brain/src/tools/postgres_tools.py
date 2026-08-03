"""Allowlisted read-only Postgres view access for exact tabular data.

Workers/chat SQL agents use this for cell/row-accurate answers.
Aggregations still go through Cube.js when available.
Falls back to extracted_tables when views/registry are missing.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
from typing import Any, Dict, List, Set

import structlog
from langchain_core.tools import tool

from core.config import settings

logger = structlog.get_logger(__name__)

_VIEW_NAME_RE = re.compile(r"^view_[a-z][a-z0-9_]*$")
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
DEFAULT_ROW_LIMIT = 100
MAX_ROW_LIMIT = 500

SYSTEM_COLUMNS = [
    "id",
    "tenant_id",
    "sys_document_id",
    "sys_node_id",
    "row_index",
    "sys_user_id",
    "source_page",
    "source_bbox",
    "mapping_status",
]

# Prefer human/auto-verified rows; fall back so chat still answers during HITL backlog.
_TRUST_VERIFIED = "verified"
_TRUST_PROVISIONAL = "provisional"
_TRUST_UNVERIFIED = "unverified"
_TRUST_EMPTY = "empty"


def select_by_mapping_priority(
    rows: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], str]:
    """
    Selects highest trust rows (MAPPED over NEEDS_REVIEW over others).
    Annotates each returned row with trust_level.
    """
    if not rows:
        return [], _TRUST_EMPTY

    mapped = [r for r in rows if r.get("mapping_status") == "MAPPED"]
    if mapped:
        annotated = [dict(r, trust_level=_TRUST_VERIFIED) for r in mapped]
        return annotated, _TRUST_VERIFIED

    review = [r for r in rows if r.get("mapping_status") == "NEEDS_REVIEW"]
    if review:
        annotated = [dict(r, trust_level=_TRUST_PROVISIONAL) for r in review]
        return annotated, _TRUST_PROVISIONAL

    annotated = [dict(r, trust_level=_TRUST_UNVERIFIED) for r in rows]
    return annotated, _TRUST_UNVERIFIED


def _pack_exact_result(
    *,
    view: str,
    tenant_id: str,
    document_id: str,
    rows: List[Dict[str, Any]],
    note: str | None = None,
) -> str:
    selected, trust = select_by_mapping_priority(rows)
    payload: Dict[str, Any] = {
        "view": view,
        "tenant_id": tenant_id,
        "document_id": document_id or None,
        "data_quality": trust,
        "row_count": len(selected),
        "rows": selected,
    }
    if trust == _TRUST_PROVISIONAL:
        payload["quality_note"] = "Provisional data (NEEDS_REVIEW): numbers are unverified."
    if note:
        payload["note"] = note
    return json.dumps(payload, indent=2, default=str)


def _database_dsn() -> str:
    url = settings.database_url or ""
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url.split("://", 1)[1]
    return url


async def _connect():
    """Fresh connection for tool queries — never reuse uvicorn's asyncpg pool."""
    import asyncpg

    return await asyncpg.connect(_database_dsn())


def _run_async(coro):
    """
    Run an async coroutine from sync LangChain tool context.
    Uses a dedicated event loop/thread so it does not touch the shared app pool.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _registry_path() -> str:
    env_path = os.environ.get("SCHEMA_REGISTRY_PATH", "")
    if env_path and os.path.exists(env_path):
        return env_path
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.normpath(
            os.path.join(here, "..", "..", "..", "schema-aligner", "src", "core", "registry.json")
        ),
        "/schema-aligner/src/core/registry.json",
        "/app/schema-aligner/src/core/registry.json",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def _load_registry() -> Dict[str, Any]:
    path = _registry_path()
    if not os.path.exists(path):
        logger.warning("Schema registry not found for exact SQL", path=path)
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed to load schema registry", error=str(e))
        return {}


def _view_name_for_table(target_table: str) -> str:
    if target_table.startswith("view_"):
        return target_table
    return f"view_{target_table}"


def get_allowed_views() -> Dict[str, Dict[str, str]]:
    registry = _load_registry()
    allowed: Dict[str, Dict[str, str]] = {}
    for table, cols in registry.items():
        if not isinstance(cols, dict):
            continue
        flat = {k: (v if isinstance(v, str) else "str") for k, v in cols.items() if isinstance(k, str)}
        allowed[_view_name_for_table(table)] = flat
    return allowed


def is_allowed_view(view_name: str) -> bool:
    if not view_name or not _VIEW_NAME_RE.match(view_name):
        return False
    return view_name in get_allowed_views()


def _validate_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid identifier: {name}")
    return name


def _parse_filters(filters_json: str, allowed_columns: Set[str]) -> Dict[str, Any]:
    if not filters_json or not filters_json.strip():
        return {}
    try:
        raw = json.loads(filters_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"filters_json must be valid JSON object: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError("filters_json must be a JSON object of equality filters")

    out: Dict[str, Any] = {}
    for k, v in raw.items():
        key = str(k)
        if key not in allowed_columns:
            raise ValueError(f"Filter column '{key}' is not allowed on this view")
        if isinstance(v, (dict, list)):
            raise ValueError(f"Filter value for '{key}' must be a scalar")
        out[key] = v
    return out


async def _list_target_tables_from_db() -> List[str]:
    conn = await _connect()
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT target_table
            FROM extracted_tables
            WHERE target_table IS NOT NULL AND target_table <> ''
            ORDER BY target_table
            LIMIT 200
            """
        )
        return [r["target_table"] for r in rows]
    finally:
        await conn.close()


async def _fetch_extracted_rows(
    tenant_id: str,
    document_id: str,
    target_table: str,
    limit: int,
) -> List[Dict[str, Any]]:
    clauses = ["tenant_id = $1"]
    args: List[Any] = [tenant_id]
    idx = 2
    if document_id:
        clauses.append(f"document_id = ${idx}")
        args.append(document_id)
        idx += 1
    if target_table:
        clauses.append(f"target_table = ${idx}")
        args.append(target_table)
        idx += 1
    where_sql = " AND ".join(clauses)
    query = f"""
        SELECT id, tenant_id, document_id AS sys_document_id, node_id AS sys_node_id,
               row_index, source_page, source_bbox, target_table, mapping_status,
               strict_columns, unmapped_jsonb
        FROM extracted_tables
        WHERE {where_sql}
        ORDER BY
          CASE mapping_status WHEN 'MAPPED' THEN 0 WHEN 'NEEDS_REVIEW' THEN 1 ELSE 2 END,
          row_index ASC NULLS LAST
        LIMIT ${idx}
    """
    args.append(limit)
    conn = await _connect()
    try:
        rows = await conn.fetch(query, *args)
    finally:
        await conn.close()
    results = []
    for row in rows:
        item = dict(row)
        for k, v in list(item.items()):
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif isinstance(v, memoryview):
                item[k] = bytes(v).decode("utf-8", errors="replace")
        strict = item.get("strict_columns")
        if isinstance(strict, dict):
            for sk, sv in strict.items():
                if item.get(sk) is None and sv is not None:
                    item[sk] = sv

        unmapped = item.get("unmapped_jsonb")
        if isinstance(unmapped, dict):
            for uk, uv in unmapped.items():
                if item.get(uk) is None and uv is not None and uv != "":
                    item[uk] = uv

        extracted_nums = _extract_numbers_from_blob(unmapped) or _extract_numbers_from_blob(item.get("source_text"))
        for ek, ev in extracted_nums.items():
            if item.get(ek) is None:
                item[ek] = ev

        results.append(item)
    return results


async def _fetch_rows(
    view_name: str,
    tenant_id: str,
    document_id: str,
    filters: Dict[str, Any],
    limit: int,
) -> List[Dict[str, Any]]:
    _validate_ident(view_name)
    clauses = ["tenant_id = $1"]
    args: List[Any] = [tenant_id]
    idx = 2

    if document_id:
        clauses.append(f"sys_document_id = ${idx}")
        args.append(document_id)
        idx += 1

    for col, val in filters.items():
        _validate_ident(col)
        clauses.append(f"{col} = ${idx}")
        args.append(val)
        idx += 1

    where_sql = " AND ".join(clauses)
    query = f"""
        SELECT *
        FROM {view_name}
        WHERE {where_sql}
        ORDER BY
          CASE mapping_status WHEN 'MAPPED' THEN 0 WHEN 'NEEDS_REVIEW' THEN 1 ELSE 2 END,
          row_index ASC NULLS LAST
        LIMIT ${idx}
    """
    args.append(limit)

    conn = await _connect()
    try:
        rows = await conn.fetch(query, *args)
    finally:
        await conn.close()

    if not rows and document_id:
        logger.info("Exact view yielded 0 rows for document; auto-discovering available document tables", view=view_name, document_id=document_id)
        conn = await _connect()
        try:
            avail = await conn.fetch(
                "SELECT DISTINCT target_table FROM extracted_tables WHERE document_id = $1 AND target_table IS NOT NULL AND target_table <> '' LIMIT 5",
                document_id
            )
            avail_tables = [r["target_table"] for r in avail]
            # Prioritize core financial statements (balance sheet, income statement, cash flow)
            core_order = ["standardized_balance_sheet", "standardized_income_statement", "standardized_cash_flow", "vendor_invoice_headers"]
            avail_tables.sort(key=lambda t: core_order.index(t) if t in core_order else 99)
        finally:
            await conn.close()

        if avail_tables:
            for cand_t in avail_tables:
                alt_view = f"view_{cand_t}" if not cand_t.startswith("view_") else cand_t
                if alt_view != view_name and is_allowed_view(alt_view):
                    logger.info("Serving alternative table present for document", alt_view=alt_view, document_id=document_id)
                    alt_query = f"""
                        SELECT *
                        FROM {alt_view}
                        WHERE tenant_id = $1 AND sys_document_id = $2
                        ORDER BY
                          CASE mapping_status WHEN 'MAPPED' THEN 0 WHEN 'NEEDS_REVIEW' THEN 1 ELSE 2 END,
                          row_index ASC NULLS LAST
                        LIMIT $3
                    """
                    conn = await _connect()
                    try:
                        candidate_rows = await conn.fetch(alt_query, tenant_id, document_id, limit)
                        if candidate_rows:
                            rows = candidate_rows
                            break
                    finally:
                        await conn.close()

        if not rows:
            logger.info("Falling back to tenant-wide search for view", view=view_name)
            fallback_clauses = ["tenant_id = $1"]
            fallback_args: List[Any] = [tenant_id]
            f_idx = 2
            for col, val in filters.items():
                _validate_ident(col)
                fallback_clauses.append(f"{col} = ${f_idx}")
                fallback_args.append(val)
                f_idx += 1
            f_where = " AND ".join(fallback_clauses)
            f_query = f"""
                SELECT *
                FROM {view_name}
                WHERE {f_where}
                ORDER BY
                  CASE mapping_status WHEN 'MAPPED' THEN 0 WHEN 'NEEDS_REVIEW' THEN 1 ELSE 2 END,
                  row_index ASC NULLS LAST
                LIMIT ${f_idx}
            """
            fallback_args.append(limit)
            conn = await _connect()
            try:
                rows = await conn.fetch(f_query, *fallback_args)
            finally:
                await conn.close()

    return _clean_rows(rows)

def _extract_numbers_from_blob(blob: Any) -> Dict[str, float]:
    """Parse numeric key-value pairs from raw unmapped JSON/text blobs."""
    out: Dict[str, float] = {}
    if not blob:
        return out
    text = str(blob)
    import re
    matches = re.findall(r'"([a-zA-Z0-9_]{3,40})"\s*:\s*"?([$-]?[\d,]+\.?\d*)"?', text)
    for k, v in matches:
        k_lower = k.lower()
        if any(kw in k_lower for kw in ("asset", "revenue", "income", "liability", "equity", "cash", "debt", "profit", "amount", "total", "subtotal", "tax", "eps", "cost", "expense", "margin", "payable", "receivable")):
            try:
                clean_v = v.replace("$", "").replace(",", "").strip()
                if clean_v and clean_v != "-":
                    num = float(clean_v)
                    out[k_lower] = num
            except ValueError:
                pass
    return out


def _clean_rows(rows: List[Any]) -> List[Dict[str, Any]]:
    results = []
    for row in rows:
        item = dict(row)
        for k, v in list(item.items()):
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif isinstance(v, memoryview):
                item[k] = bytes(v).decode("utf-8", errors="replace")
        
        # Unpack unmapped_jsonb fields if present
        unmapped = item.get("unmapped_jsonb")
        if isinstance(unmapped, dict):
            for uk, uv in unmapped.items():
                if item.get(uk) is None and uv is not None and uv != "":
                    item[uk] = uv
        elif isinstance(unmapped, list):
            for entry in unmapped:
                if isinstance(entry, dict):
                    for uk, uv in entry.items():
                        if item.get(uk) is None and uv is not None and uv != "":
                            item[uk] = uv

        # Fallback: Extract numbers from raw source_text or unmapped_jsonb blob if key fields are null
        extracted_nums = _extract_numbers_from_blob(unmapped) or _extract_numbers_from_blob(item.get("source_text"))
        for ek, ev in extracted_nums.items():
            if item.get(ek) is None:
                item[ek] = ev

        results.append(item)
    return results


@tool
def list_exact_views() -> str:
    """
    Lists allowlisted Postgres views (exact tabular data) and their columns.
    Use this before query_exact_rows to pick the correct view for row-accurate answers.
    """
    allowed = get_allowed_views()
    lines = ["Exact Postgres access (read-only, tenant-scoped):\n"]

    if allowed:
        for view_name in sorted(allowed.keys()):
            cols = allowed[view_name]
            lines.append(f"- {view_name}")
            lines.append(f"  system: {', '.join(SYSTEM_COLUMNS)}")
            for col, typ in cols.items():
                lines.append(f"  - {col} ({typ})")
    else:
        lines.append(
            "No schema-registry views loaded. Use view_name='extracted_tables' "
            "or view_<target_table>; data is read from extracted_tables."
        )
        try:
            tables = _run_async(_list_target_tables_from_db())
            if tables:
                lines.append("\nAvailable target_table values:")
                for t in tables:
                    lines.append(f"- {t}")
        except Exception as e:
            lines.append(f"(Could not list extracted_tables targets: {e})")

    lines.append(
        "\nPrefer query_exact_rows for exact values. "
        "Results prefer mapping_status=MAPPED; if none match, NEEDS_REVIEW is returned as provisional. "
        "Use Cube only when Cube is available for aggregations."
    )
    return "\n".join(lines)


@tool
def query_exact_rows(
    view_name: str,
    tenant_id: str,
    document_id: str = "",
    filters_json: str = "{}",
    limit: int = DEFAULT_ROW_LIMIT,
) -> str:
    """
    Safe SELECT for exact extracted data. tenant_id is always enforced.
    Prefer view_* names. If views are missing, use extracted_tables or view_<target_table>.
    """
    view_name = (view_name or "").strip()
    safe_limit = max(1, min(int(limit or DEFAULT_ROW_LIMIT), MAX_ROW_LIMIT))

    if view_name in ("extracted_tables", "raw_extracted_tables"):
        try:
            filters = json.loads(filters_json or "{}")
            if not isinstance(filters, dict):
                filters = {}
        except json.JSONDecodeError:
            return "SQL Error: filters_json must be valid JSON object"
        target_table = str(filters.get("target_table") or "")
        try:
            rows = _run_async(
                _fetch_extracted_rows(tenant_id, document_id or "", target_table, safe_limit)
            )
        except Exception as e:
            logger.error("query_extracted_tables failed", error=str(e))
            return f"SQL Error: {e}"
        return _pack_exact_result(
            view="extracted_tables",
            tenant_id=tenant_id,
            document_id=document_id or "",
            rows=rows,
        )

    def _fallback_extracted(target: str, note: str) -> str:
        rows = _run_async(
            _fetch_extracted_rows(tenant_id, document_id or "", target, safe_limit)
        )
        return _pack_exact_result(
            view=f"extracted_tables:{target or '*'}",
            tenant_id=tenant_id,
            document_id=document_id or "",
            rows=rows,
            note=note,
        )

    if not is_allowed_view(view_name):
        target = view_name[5:] if view_name.startswith("view_") else view_name
        try:
            return _fallback_extracted(
                target,
                "Served from extracted_tables because view was not allowlisted/missing",
            )
        except Exception as e:
            return (
                f"SQL Error: view '{view_name}' is not allowlisted and fallback failed: {e}"
            )

    allowed_cols = set(SYSTEM_COLUMNS) | set(get_allowed_views().get(view_name, {}).keys())
    try:
        filters = _parse_filters(filters_json, allowed_cols)
    except ValueError as e:
        return f"SQL Error: {e}"

    filters.pop("tenant_id", None)

    try:
        rows = _run_async(
            _fetch_rows(view_name, tenant_id, document_id or "", filters, safe_limit)
        )
    except Exception as e:
        logger.error("query_exact_rows failed", error=str(e), view=view_name)
        target = view_name[5:] if view_name.startswith("view_") else ""
        try:
            return _fallback_extracted(target, f"View query failed ({e}); extracted_tables fallback")
        except Exception as e2:
            return f"SQL Error: {e}; fallback also failed: {e2}"

    return _pack_exact_result(
        view=view_name,
        tenant_id=tenant_id,
        document_id=document_id or "",
        rows=rows,
    )
