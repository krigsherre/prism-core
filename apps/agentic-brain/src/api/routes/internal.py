from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from llm.factory import LLMFactory, ModelTier
import structlog
from typing import Optional

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/internal", tags=["internal"])

class MetadataExtractionRequest(BaseModel):
    text: str = Field(description="The first few pages of the document text.")

class MetadataExtraction(BaseModel):
    company_name: Optional[str] = Field(default=None, description="The full legal name of the company if present, otherwise null.")
    ticker: Optional[str] = Field(default=None, description="The stock ticker symbol if present, otherwise null.")
    fiscal_period: Optional[str] = Field(default=None, description="The fiscal period (e.g. Q1 2025, FY 2024), otherwise null.")
    document_type: Optional[str] = Field(default=None, description="The document type (e.g. 10-K, 10-Q, Earnings Call Transcript), otherwise null.")

@router.post("/extract-metadata", response_model=MetadataExtraction)
async def extract_metadata(req: MetadataExtractionRequest):
    """
    Extracts core financial metadata from raw document text using the LLM.
    Used by storage-sync worker at ingestion time.
    """
    logger.info("Extracting document metadata at ingestion time.")
    try:
        llm = LLMFactory.get_structured_llm(MetadataExtraction, tier=ModelTier.STANDARD)
        
        system_prompt = (
            "You are an expert financial analyst. Read the following document text (which may be messy OCR or raw text) "
            "and extract the company name, stock ticker, fiscal period, and document type. "
            "If a field is not confidently found, return null for that field. Do NOT hallucinate."
        )
        
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Document Text:\n{req.text}")
        ]
        
        if hasattr(llm, "ainvoke"):
            result = await llm.ainvoke(messages)
        else:
            result = llm.invoke(messages)
            
        return result
    except Exception as e:
        logger.error("Failed to extract metadata", error=str(e))
        raise HTTPException(status_code=500, detail="Metadata extraction failed")


class HitlStatusUpdate(BaseModel):
    document_id: str
    status: str = "RESOLVED"

@router.post("/hitl-resolve")
async def hitl_resolve(req: HitlStatusUpdate):
    """Mark a HITL request as resolved by document_id. Called by schema-aligner after approve/divert."""
    from core.db import db_client
    if not db_client.pool:
        await db_client.connect()
    async with db_client.pool.acquire() as conn:
        await conn.execute(
            "UPDATE hitl_requests SET status = $1 WHERE document_id = $2",
            req.status, req.document_id
        )
    logger.info("HITL request marked resolved", document_id=req.document_id, status=req.status)
    return {"ok": True}
