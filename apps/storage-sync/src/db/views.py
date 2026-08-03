import json
import os
import structlog
from sqlalchemy import text
from .postgres import AsyncSessionLocal

logger = structlog.get_logger(__name__)

async def generate_schema_views():
    """Generate Postgres views from schema-aligner registry.json over extracted_tables."""
    registry_path = _get_registry_path()
    
    if not os.path.exists(registry_path):
        logger.warning(f"Schema registry not found at {registry_path}, skipping view generation.")
        return
        
    schemas = _load_schemas(registry_path)
    
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for target_table, schema_def in schemas.items():
                try:
                    await _create_view_for_schema(session, target_table, schema_def)
                except Exception as e:
                    logger.error("Failed to generate view", view_name=target_table, error=str(e))

def _get_registry_path() -> str:
    env_path = os.environ.get("SCHEMA_REGISTRY_PATH", "")
    if env_path and os.path.exists(env_path):
        return env_path

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.normpath(os.path.join(here, "..", "..", "..", "schema-aligner", "src", "core", "registry.json")),
        "/schema-aligner/src/core/registry.json",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]

def _load_schemas(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)

async def _create_view_for_schema(session, target_table: str, schema_def: dict):
    view_name = target_table if target_table.startswith("view_") else f"view_{target_table}"
    
    enriched_schema = _enrich_schema(schema_def)
    if not enriched_schema:
        return
        
    columns_str = _build_column_selections(enriched_schema)
    
    drop_sql = f"DROP VIEW IF EXISTS {view_name} CASCADE;"
    create_sql = _build_create_view_sql(view_name, target_table, columns_str)
    
    await session.execute(text(drop_sql))
    await session.execute(text(create_sql))
    logger.info("Generated PostgreSQL view", view_name=view_name)

def _enrich_schema(schema_def: dict) -> dict:
    if not schema_def: 
        return {}
        
    context_fields = {
        "context_entity_name": "str",
        "context_reporting_period": "str",
        "context_currency": "str",
        "context_scale": "str"
    }
    
    return {**context_fields, **schema_def}

def _build_column_selections(schema_def: dict) -> str:
    columns_sql = []
    for col_name, val_type in schema_def.items():
        if isinstance(val_type, dict): 
            continue
            
        columns_sql.append(_build_single_column_sql(col_name, val_type))
        
    if not columns_sql:
        return ""
        
    return ",\n                        " + ",\n                        ".join(columns_sql)

SYNONYM_SQL_MAP: dict = {
    "net_income": ["net_income", "net_income_loss", "consolidated_net_income", "net_earnings", "Net Income"],
    "total_revenue": ["total_revenue", "total_net_sales", "revenue", "net_sales", "Total Net Sales", "Total Revenue"],
    "revenue_from_operations": ["revenue_from_operations", "operating_revenue", "total_revenue", "net_sales"],
    "cost_of_goods_sold": ["cost_of_goods_sold", "cost_of_sales", "cogs", "Cost of Sales"],
    "gross_profit": ["gross_profit", "gross_margin", "Gross Profit"],
    "operating_income": ["operating_income", "operating_profit", "income_from_operations", "Operating Income"],
    "tax_expense": ["tax_expense", "provision_for_income_taxes", "income_tax_expense", "Income Taxes"],
    "eps_basic": ["eps_basic", "basic_eps", "basic_earnings_per_share"],
    "eps_diluted": ["eps_diluted", "diluted_eps", "diluted_earnings_per_share"],
    "net_cash_from_operating_activities": ["net_cash_from_operating_activities", "operating_cash_flow", "cash_from_operations", "Net Cash from Operating Activities"],
    "share_based_compensation": ["share_based_compensation", "stock_based_compensation"],
    "depreciation_and_amortization_cf": ["depreciation_and_amortization_cf", "depreciation_and_amortization"],
    "change_in_operating_assets_liabilities": ["change_in_operating_assets_liabilities", "working_capital_changes"],
    "capital_expenditure": ["capital_expenditure", "capex", "capital_expenditures"],
    "net_cash_from_investing_activities": ["net_cash_from_investing_activities", "investing_cash_flow", "Net Cash from Investing Activities"],
    "net_cash_from_financing_activities": ["net_cash_from_financing_activities", "financing_cash_flow", "Net Cash from Financing Activities"],
}

def _build_single_column_sql(col_name: str, val_type: str) -> str:
    v_lower = val_type.lower() if isinstance(val_type, str) else "str"
    synonyms = SYNONYM_SQL_MAP.get(col_name, [col_name])
    if col_name not in synonyms:
        synonyms = [col_name] + synonyms
        
    coalesce_parts = []
    for s in synonyms:
        s_title = s.replace("_", " ").title()
        s_lower = s.lower()
        keys_to_try = set([s, s_title, s_lower, s.replace("_", " ")])
        for k in keys_to_try:
            coalesce_parts.append(f"t.strict_columns->>'{k}'")
            coalesce_parts.append(f"t.unmapped_jsonb->>'{k}'")
    val_expr = f"COALESCE({', '.join(coalesce_parts)})"
    
    if v_lower in ["int", "float"]:
        cast_type = "integer" if v_lower == "int" else "numeric"
        clean_expr = f"CASE WHEN regexp_replace({val_expr}, '[^0-9]', '', 'g') = '' THEN NULL WHEN {val_expr} LIKE '%(%)%' THEN '-' || regexp_replace({val_expr}, '[^0-9.]', '', 'g') WHEN {val_expr} LIKE '%-%' THEN '-' || regexp_replace({val_expr}, '[^0-9.]', '', 'g') ELSE regexp_replace({val_expr}, '[^0-9.]', '', 'g') END"
        return f"({clean_expr})::{cast_type} AS {col_name}"
        
    elif v_lower in ["datetime", "bool", "boolean"]:
        cast_type = "timestamp" if v_lower == "datetime" else "boolean"
        clean_expr = f"CASE WHEN BTRIM(LOWER({val_expr})) IN ('', 'na', 'n/a', 'none', 'null', 'nan', 'unknown', '-') THEN NULL ELSE {val_expr} END"
        return f"({clean_expr})::{cast_type} AS {col_name}"
        
    elif v_lower == "dict":
        return f"COALESCE(t.strict_columns->'{col_name}', t.unmapped_jsonb->'{col_name}') AS {col_name}"
        
    else:
        return f"NULLIF({val_expr}, '')::text AS {col_name}"

def _build_create_view_sql(view_name: str, target_table: str, columns_str: str) -> str:
    return f"""
    CREATE OR REPLACE VIEW {view_name} AS
    SELECT 
         t.id, 
         t.tenant_id, 
         t.document_id AS sys_document_id,
        t.node_id AS sys_node_id,
        t.row_index,
        t.user_id AS sys_user_id,
        t.source_page,
        t.source_bbox,
        t.mapping_status{columns_str}
    FROM extracted_tables t
    WHERE t.target_table = '{target_table}';
    """