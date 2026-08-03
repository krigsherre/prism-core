from typing import Any, Dict, Optional
import httpx
import structlog

logger = structlog.get_logger(__name__)


class MetadataExtractionService:
    """
    Service for extracting document-level metadata (company name, ticker, fiscal period)
    via internal HTTP call to agentic-brain.
    """

    def __init__(self, endpoint_url: str = "http://agentic-brain:8000/api/internal/extract-metadata", timeout: float = 15.0) -> None:
        self.endpoint_url = endpoint_url
        self.timeout = timeout

    async def extract_metadata(self, sample_text: str, document_id: str) -> Dict[str, Optional[str]]:
        """Call agentic-brain internal API to extract metadata from sample document text."""
        result: Dict[str, Optional[str]] = {
            "company_name": None,
            "ticker": None,
            "fiscal_period": None,
        }
        if not sample_text:
            return result

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.endpoint_url,
                    json={"text": sample_text[:10000]},
                )
                if resp.status_code == 200:
                    meta_data = resp.json()
                    result["company_name"] = meta_data.get("company_name")
                    result["ticker"] = meta_data.get("ticker")
                    result["fiscal_period"] = meta_data.get("fiscal_period")
                    logger.info("Extracted metadata", metadata=meta_data, document_id=document_id)
        except Exception as e:
            logger.error("Failed to extract metadata via internal API", error=str(e), document_id=document_id)

        return result
