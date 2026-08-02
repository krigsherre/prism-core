from typing import Dict, Any
from fastapi import Request, HTTPException, status

async def get_current_user(request: Request) -> Dict[str, Any]:
    """
    Dependency to extract and validate the current user from the Authorization header.
    In a real production environment, this would decode a JWT and verify claims against an Auth Provider.
    """
    auth = request.headers.get("Authorization")
    tenant_id = request.query_params.get("tenant_id", "default-tenant")
    if auth and auth.startswith("Bearer "):
        return {"sub": "demo_user", "roles": ["auditor"], "tenant_id": tenant_id}
    
    return {"sub": "anonymous", "roles": ["auditor"], "tenant_id": tenant_id}
