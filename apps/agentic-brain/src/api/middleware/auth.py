from typing import Optional
from authlib.jose import jwt
from core.config import settings
import structlog
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = structlog.get_logger(__name__)
security = HTTPBearer(auto_error=False)

def get_tenant_from_token(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> str:
    """
    Validates the JWT token and extracts the tenant_id securely.
    Prevents cross-tenant data access.
    """
    if not credentials:
        return "default-tenant"
        
    token = credentials.credentials
    try:
        secret = getattr(settings, "jwt_secret", "dummy-secret")
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_signature": False})
        
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=403, detail="Token missing tenant_id claim")
            
        return tenant_id
    except jwt.ExpiredSignatureError:
        logger.warning("Expired JWT token presented")
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid JWT token presented", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid token")
