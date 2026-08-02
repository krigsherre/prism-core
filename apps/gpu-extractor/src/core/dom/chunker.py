import fitz
import structlog
from typing import List, Dict, Any, cast
from config.settings import settings

logger = structlog.get_logger(__name__)

class SmartChunker:
    @classmethod
    def calculate_chunks(cls, pdf_path: str, static_chunk_size: int = settings.chunk_size_pages) -> List[Dict[str, Any]]:
        """
        Dynamically breaks a PDF into chunks.
        Returns a list of dicts:
        [
            {"start_page": 0, "end_page": 11, "injected_context": ""},
            {"start_page": 12, "end_page": 20, "injected_context": "Last known section header"}
        ]
        """
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        chunks = []
        current_start = 0
        last_known_section = ""
        
        try:
            while current_start < total_pages:
                current_end = cls._find_safe_page_break(doc, current_start, static_chunk_size, total_pages)
                last_known_section = cls._extract_last_known_header(doc, current_start, current_end, last_known_section)
                
                chunks.append({
                    "start_page": current_start,
                    "end_page": current_end,
                    "injected_context": last_known_section if current_start > 0 else ""
                })
                
                current_start = current_end + 1
        finally:
            doc.close()
            
        return chunks

    @classmethod
    def _find_safe_page_break(cls, doc: fitz.Document, current_start: int, static_chunk_size: int, total_pages: int) -> int:
        current_end = min(current_start + static_chunk_size - 1, total_pages - 1)
        
        while current_end < total_pages - 1:
            page = doc.load_page(current_end)
            tables = page.find_tables()
            
            spans_bottom = False
            if tables and hasattr(tables, "tables"):
                for tab in tables.tables:
                    if tab.bbox[3] > page.rect.height * settings.table_span_threshold_bottom:
                        spans_bottom = True
                        break
                        
            if not spans_bottom:
                break
                
            next_page = doc.load_page(current_end + 1)
            next_tables = next_page.find_tables()
            
            continues_top = False
            if next_tables and hasattr(next_tables, "tables"):
                for ntab in next_tables.tables:
                    if ntab.bbox[1] < next_page.rect.height * settings.table_span_threshold_top:
                        continues_top = True
                        break
                        
            if continues_top:
                current_end += 1
            else:
                current_end += 1
                break
                
        return min(current_end, total_pages - 1)

    @classmethod
    def _extract_last_known_header(cls, doc: fitz.Document, start_page: int, end_page: int, fallback_header: str) -> str:
        last_known = fallback_header
        for p in range(start_page, end_page + 1):
            page = doc.load_page(p)
            page_dict = cast(Dict[str, Any], page.get_text("dict"))
            blocks = page_dict.get("blocks", [])
            
            for b in blocks:
                if "lines" not in b:
                    continue
                for l in b["lines"]:
                    for s in l.get("spans", []):
                        if s["size"] > 11 or "bold" in s["font"].lower():
                            text = s["text"].strip()
                            if 3 < len(text) < 100:
                                last_known = text
        return last_known