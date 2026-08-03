# pyright: reportAttributeAccessIssue=false
import os
import tempfile
import asyncio
import structlog
import fitz
from PIL import Image
from contextlib import asynccontextmanager
from tenacity import retry, stop_after_attempt, wait_exponential

from core.dom.preprocessor import OmniPreprocessor
from core.ml.layout import LayoutSlicer
from core.ml.adapters import ExtractorFactory
from core.dom.post_processor import DOMPostProcessor
from core.dom.builder import DOMBuilder
from core.dom.table_json import TableJSON, normalize_table_content
from typing import Any, List, Tuple, Dict, AsyncGenerator
import proto.prism.v1.dom_pb2 as dom_pb2

logger = structlog.get_logger(__name__)


class ExtractionService:
    """
    Business logic layer for the GPU Extractor.
    Receives dependencies via constructor (Dependency Injection).
    """
    def __init__(
        self,
        s3_client,
        preprocessor: OmniPreprocessor,
        layout_slicer: LayoutSlicer,
        extractor_factory: ExtractorFactory,
        post_processor: DOMPostProcessor,
        dynamic_batcher: Any = None,
    ):
        self.s3 = s3_client
        self.preprocessor = preprocessor
        self.layout_slicer = layout_slicer
        self.extractor_factory = extractor_factory
        self.post_processor = post_processor
        self.dynamic_batcher = dynamic_batcher

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _download_s3_to_disk(self, bucket: str, key: str, tmp_path: str):
        await asyncio.to_thread(self.s3.download_file, bucket, key, tmp_path)

    @asynccontextmanager
    async def _managed_document_download(self, s3_uri: str) -> AsyncGenerator[Tuple[str, str], None]:
        path_parts = s3_uri.replace("s3://", "").split("/")
        bucket = path_parts[0]
        key = "/".join(path_parts[1:])
        
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(key)[1])
        os.close(tmp_fd)
        
        norm_path = None
        try:
            await self._download_s3_to_disk(bucket, key, tmp_path)
            norm_path, directive = await asyncio.to_thread(self.preprocessor.preprocess, tmp_path)
            yield norm_path, directive
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            try:
                if norm_path and norm_path != tmp_path and os.path.exists(norm_path):
                    os.remove(norm_path)
            except Exception as e:
                logger.error(f"Failed to cleanup norm_path: {e}")

    async def process_document(self, s3_uri: str, document_id: str = "", metadata: dict | None = None, start_page: int | None = None, end_page: int | None = None, injected_context: str = "") -> dom_pb2.DocumentDOM:
        """
        Executes the entire extraction pipeline for a single document asynchronously.
        """
        logger.info(f"Processing document: {s3_uri}")
        
        async with self._managed_document_download(s3_uri) as (norm_path, directive):
            builder = DOMBuilder()
            if directive == "PDF_LAYOUT":
                await self._process_pdf_layout(builder, norm_path, start_page, end_page, injected_context)
            elif directive == "RAW_TEXT":
                self._process_raw_text(builder, norm_path)

            return self._finalize_dom(builder, document_id, metadata)

    async def _process_pdf_layout(self, builder: DOMBuilder, norm_path: str, start_page: int | None, end_page: int | None, injected_context: str):
        doc = fitz.open(norm_path)
        try:
            sp = 0 if start_page is None else start_page
            ep = (len(doc) - 1) if end_page is None else min(end_page, len(doc) - 1)

            if injected_context:
                self._inject_parent_context(builder, injected_context, sp)

            pending_nodes, promises = await self._enqueue_layout_tasks(doc, sp, ep)
            await self._resolve_gpu_promises(builder, pending_nodes, promises)
        finally:
            doc.close()

    def _inject_parent_context(self, builder: DOMBuilder, context: str, start_page: int):
        builder.add_element({
            "type": "SECTION_HEADER",
            "content": context,
            "page": start_page + 1,
            "bbox": [0.0, 0.0, 0.0, 0.0]
        })

    async def _enqueue_layout_tasks(self, doc: fitz.Document, start_page: int, end_page: int) -> Tuple[List[dict], List[asyncio.Future]]:
        pending_nodes = []
        promises = []

        async def process_page(page_num: int):
            def _heavy_cpu_work():
                import base64
                import io
                with fitz.open(doc.name) as local_doc:
                    p = local_doc.load_page(page_num)
                    px = p.get_pixmap(dpi=150)
                    img = Image.frombytes("RGB", (px.width, px.height), px.samples)
                    buffered = io.BytesIO()
                    img.save(buffered, format="JPEG", quality=90)
                    b64_image = base64.b64encode(buffered.getvalue()).decode("utf-8")
                    
                    return img, b64_image, px.width, px.height
                    
            img, b64_image, pix_w, pix_h = await asyncio.to_thread(_heavy_cpu_work)
            
            page = doc.load_page(page_num)
            boxes = await self.layout_slicer.slice_page_with_b64_async(page, b64_image, pix_w, pix_h)
            
            page_nodes = []
            page_promises = []
            for box in boxes:
                meta = self._prepare_node_metadata(box, page_num)
                await self._route_box_extraction(meta, box, page, img, page_nodes, page_promises)
                
            return page_num, page_nodes, page_promises
            
        tasks = [process_page(p) for p in range(start_page, end_page + 1)]
        pages_data = await asyncio.gather(*tasks)
        pages_data.sort(key=lambda x: x[0])

        for page_num, page_nodes, page_promises in pages_data:
            promise_offset = len(promises)
            for meta in page_nodes:
                if "promise_idx" in meta:
                    meta["promise_idx"] += promise_offset
            
            pending_nodes.extend(page_nodes)
            promises.extend(page_promises)

        return pending_nodes, promises

    def _prepare_node_metadata(self, box: Dict[str, Any], page_num: int) -> dict:
        return {
            "type": box["type"],
            "page": page_num + 1,
            "bbox": box["bbox"],
        }

    def _schema_for_box(self, box_type: str) -> Any:
        if box_type == "TABLE":
            return TableJSON
        return None

    async def _route_box_extraction(self, meta: dict, box: Dict[str, Any], page: fitz.Page, img: Image.Image, pending_nodes: List[dict], promises: List[asyncio.Future]):
        b_type = box["type"]
        bbox = box["bbox"]

        if b_type in ["TEXT", "SECTION_HEADER", "TITLE"]:
            extractor = self.extractor_factory.get_extractor(b_type)
            meta["content"] = extractor.extract(page, bbox)
            pending_nodes.append(meta)

        elif box.get("content") is not None:
            content = box["content"]
            if b_type == "TABLE":
                content = normalize_table_content(str(content))
            meta["content"] = content
            pending_nodes.append(meta)

        else:
            cropped = img.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
            target_schema = self._schema_for_box(b_type)

            extractor = self.extractor_factory.get_extractor(b_type)
            # Create a task for concurrent extraction against vLLM
            future = asyncio.create_task(extractor.extract_async(cropped, target_schema))
            promises.append(future)
            meta["promise_idx"] = len(promises) - 1
            pending_nodes.append(meta)

    async def _resolve_gpu_promises(self, builder: DOMBuilder, pending_nodes: List[dict], promises: List[asyncio.Future]):
        results = []
        if promises:
            results = await asyncio.gather(*promises)

        for meta in pending_nodes:
            if "promise_idx" in meta:
                content = results[meta["promise_idx"]]
                if meta.get("type") == "TABLE":
                    content = normalize_table_content(str(content))
                meta["content"] = content
                del meta["promise_idx"]
            builder.add_element(meta)

    def _process_raw_text(self, builder: DOMBuilder, norm_path: str):
        with open(norm_path, "r") as f:
            content = f.read()
            
        builder.add_element({
            "type": "TEXT",
            "content": content,
            "page": 1,
            "bbox": [0, 0, 0, 0],
        })

    def _finalize_dom(self, builder: DOMBuilder, document_id: str, metadata: dict | None) -> dom_pb2.DocumentDOM:
        pb_dom = builder.to_protobuf()
        
        if document_id:
            pb_dom.document_id = document_id
            
        if metadata:
            for k, v in metadata.items():
                pb_dom.metadata[k] = v
                
        return self.post_processor.process(pb_dom)