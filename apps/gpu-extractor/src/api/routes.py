from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class HealthResponse(BaseModel):
    status: str

@router.get("/healthz", response_model=HealthResponse)
async def healthz():
    return HealthResponse(status="ok")

@router.get("/readyz", response_model=HealthResponse)
async def readyz():
    return HealthResponse(status="ready")
