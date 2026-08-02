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

def _build_single_column_sql(col_name: str, val_type: str) -> str:
    v_lower = val_type.lower() if isinstance(val_type, str) else "str"
    val_expr = f"t.strict_columns->>'{col_name}'"
    
    if v_lower in ["int", "float"]:
        cast_type = "integer" if v_lower == "int" else "numeric"
        clean_expr = f"CASE WHEN regexp_replace({val_expr}, '[^0-9]', '', 'g') = '' THEN NULL WHEN {val_expr} LIKE '%(%)%' THEN '-' || regexp_replace({val_expr}, '[^0-9.]', '', 'g') WHEN {val_expr} LIKE '%-%' THEN '-' || regexp_replace({val_expr}, '[^0-9.]', '', 'g') ELSE regexp_replace({val_expr}, '[^0-9.]', '', 'g') END"
        return f"({clean_expr})::{cast_type} AS {col_name}"
        
    elif v_lower in ["datetime", "bool", "boolean"]:
        cast_type = "timestamp" if v_lower == "datetime" else "boolean"
        clean_expr = f"CASE WHEN BTRIM(LOWER(t.strict_columns->>'{col_name}')) IN ('', 'na', 'n/a', 'none', 'null', 'nan', 'unknown', '-') THEN NULL ELSE t.strict_columns->>'{col_name}' END"
        return f"({clean_expr})::{cast_type} AS {col_name}"
        
    elif v_lower == "dict":
        return f"t.strict_columns->'{col_name}' AS {col_name}"
        
    else:
        return f"NULLIF(t.strict_columns->>'{col_name}', '')::text AS {col_name}"

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