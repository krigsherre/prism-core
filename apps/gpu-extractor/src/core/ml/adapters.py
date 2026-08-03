import base64
import io
import asyncio
import httpx
from abc import ABC, abstractmethod
from typing import List, Any, Optional
from PIL import Image
import concurrent.futures
import structlog

from config.settings import settings
from core.dom.table_json import TableJSON, normalize_table_content

logger = structlog.get_logger(__name__)

TABLE_EXTRACT_PROMPT = (
    "Extract this table as JSON with keys 'headers' (array of column names) "
    "and 'rows' (array of arrays of cell strings). Return only valid JSON."
)
DEFAULT_EXTRACT_PROMPT = "Extract all text and structure from this image."
TABLE_MAX_TOKENS = 8192
DEFAULT_MAX_TOKENS = 1024

class AbstractMLExtractor(ABC):
    @abstractmethod
    def extract(self, *args: Any, **kwargs: Any) -> Any:
        pass

    @abstractmethod
    async def extract_async(self, *args: Any, **kwargs: Any) -> Any:
        pass


class PyMuPDFAdapter(AbstractMLExtractor):
    def __init__(self):
        import fitz
        self.fitz = fitz

    def extract(self, page: Any, bbox: List[float]) -> str: 
        rect = self.fitz.Rect(bbox)
        text = page.get_text("text", clip=rect)
        return text.strip()

    async def extract_async(self, page: Any, bbox: List[float]) -> str:
        return self.extract(page, bbox)


class VLLMAdapter(AbstractMLExtractor):
    """
    Generic VLLM Adapter that sends images to an OpenAI-compatible /v1/chat/completions endpoint.
    """
    def __init__(self, endpoint_url: str, model_name: str):
        self.endpoint_url = endpoint_url
        self.model_name = model_name

    def _pil_to_base64(self, img: Image.Image) -> str:
        buffered = io.BytesIO()
        if img.mode == "RGBA" or img.mode == "P":
            img = img.convert("RGB")
        img.save(buffered, format="JPEG", quality=90)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def extract(self, image: Image.Image, target_schema: Any = None) -> str:
        return self.extract_batch([image], target_schema)[0]

    def extract_batch(self, images: List[Image.Image], target_schema: Any = None) -> List[str]:
        async def _run_batch():
            tasks = [self.extract_async(img, target_schema) for img in images]
            return await asyncio.gather(*tasks)
        return asyncio.run(_run_batch())

    async def extract_async(self, image: Image.Image, target_schema: Any = None) -> str:
        is_table = self._is_table_schema(target_schema)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                b64_image = await asyncio.to_thread(self._pil_to_base64, image)
                
                if is_table or (target_schema is not None and hasattr(target_schema, "model_json_schema")):
                    prompt_text = TABLE_EXTRACT_PROMPT if is_table else "Extract structured JSON from this image."
                else:
                    prompt_text = DEFAULT_EXTRACT_PROMPT

                max_tokens = TABLE_MAX_TOKENS if is_table else DEFAULT_MAX_TOKENS
                payload = {
                    "model": self.model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}},
                                {"type": "text", "text": prompt_text}
                            ]
                        }
                    ],
                    "max_tokens": max_tokens
                }

                schema_for_guided: Optional[Any] = TableJSON if is_table else target_schema
                if schema_for_guided is not None and hasattr(schema_for_guided, "model_json_schema"):
                    try:
                        payload["guided_json"] = schema_for_guided.model_json_schema()
                    except Exception as e:
                        logger.warning(f"Failed to extract JSON schema from target_schema: {e}")

                response = await client.post(
                    f"{self.endpoint_url}/chat/completions",
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    content = content.strip()
                    if is_table:
                        content = normalize_table_content(content)
                    return content
                else:
                    logger.error(f"VLLM API Error: {response.status_code} {response.text}")
                    return TableJSON().model_dump_json() if is_table else "{}"
            except Exception as e:
                logger.error(f"VLLMAdapter extraction error: {e}")
                return TableJSON().model_dump_json() if is_table else "{}"

    def _is_table_schema(self, target_schema: Any) -> bool:
        return target_schema is TableJSON or (
            isinstance(target_schema, type) and issubclass(target_schema, TableJSON)
        ) or target_schema == "TABLE"




class ExtractorFactory:
    """
    Factory pattern to resolve the correct Tiered AbstractMLExtractor.
    - Tier 1 (PyMuPDF): TEXT, SECTION_HEADER, TITLE (0ms digital fast-path)
    - Tier 2 (vLLM Docling): KEY_VALUE, FORM, CODE, CHECKBOX (Dedicated vLLM server)
    - Tier 3 (vLLM PaddleOCR): TABLE, IMAGE (Dedicated vLLM server)
    """
    def __init__(self):
        self._fitz_adapter = PyMuPDFAdapter()
        self._docling_adapter: Any = None
        self._paddle_adapter: Any = None

    def get_extractor(self, box_type: str) -> AbstractMLExtractor:
        if box_type in ["TEXT", "SECTION_HEADER", "TITLE"]:
            return self._fitz_adapter
        elif box_type in ["KEY_VALUE", "FORM", "CODE", "CHECKBOX"]:
            if self._docling_adapter is None:
                self._docling_adapter = VLLMAdapter(
                    endpoint_url=settings.vllm_docling_url,
                    model_name="docling-project/SmolDocling-256M-preview"
                )
            return self._docling_adapter
        elif box_type in ["TABLE", "IMAGE"]:
            if self._paddle_adapter is None:
                self._paddle_adapter = VLLMAdapter(
                    endpoint_url=settings.vllm_paddleocr_url,
                    model_name="PaddleOCR-VL-1.6-0.9B"
                )
            return self._paddle_adapter
        else:
            return self._fitz_adapter
