import json
import os
import yaml

def generate_cubes():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    registry_path = os.path.join(base_dir, "apps", "schema-aligner", "src", "core", "registry.json")
    out_dir = os.path.join(base_dir, "infra", "cube", "model", "cubes")
    
    os.makedirs(out_dir, exist_ok=True)
    
    with open(registry_path, "r") as f:
        schemas = json.load(f)
        
    for table_name, schema_def in schemas.items():
        if not isinstance(schema_def, dict): continue

        view_name = table_name if table_name.startswith("view_") else f"view_{table_name}"
        
        cube_name = "".join(x.title() for x in view_name.split("_"))
        
        dimensions = [
            {"name": "id", "type": "string", "sql": "id", "primary_key": True},
            {"name": "tenant_id", "type": "string", "sql": "tenant_id"},
            {"name": "sys_document_id", "type": "string", "sql": "sys_document_id"}
        ]
        
        measures = [
            {"name": "count", "type": "count"}
        ]
        
        for col_name, col_type in schema_def.items():
            col_type = col_type.lower() if isinstance(col_type, str) else "str"
            
            if col_type in ["int", "float"]:
                dimensions.append({"name": col_name, "type": "number", "sql": col_name})
                measures.append({"name": f"total_{col_name}", "type": "sum", "sql": col_name})
                measures.append({"name": f"avg_{col_name}", "type": "avg", "sql": col_name})
            elif col_type == "datetime":
                dimensions.append({"name": col_name, "type": "time", "sql": col_name})
            elif col_type in ["bool", "boolean"]:
                dimensions.append({"name": col_name, "type": "boolean", "sql": col_name})
            elif col_type == "dict":
                dimensions.append({"name": col_name, "type": "string", "sql": f"CAST({col_name} AS TEXT)"})
            else:
                dimensions.append({"name": col_name, "type": "string", "sql": col_name})
                
        cube_def = {
            "cubes": [
                {
                    "name": cube_name,
                    "sql": f"SELECT * FROM {view_name}",
                    "measures": measures,
                    "dimensions": dimensions
                }
            ]
        }
        
        out_file = os.path.join(out_dir, f"{view_name}.yml")
        with open(out_file, "w") as f:
            yaml.dump(cube_def, f, default_flow_style=False, sort_keys=False)
            
    print(f"Successfully generated {len(schemas)} cube models in {out_dir}")

if __name__ == "__main__":
    generate_cubes()
