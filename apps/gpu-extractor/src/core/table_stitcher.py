"""Cross-page table reassembly and header/scale footnote propagation."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)

_SCALE_PATTERNS = [
    r"in\s+millions?",
    r"usd\s+thousands?",
    r"in\s+thousands?",
    r"\$\s*in\s*millions?",
    r"\$\s*in\s*thousands?",
]


def extract_context_scale_from_text(text: str) -> Optional[str]:
    """Find scale footnotes in parent text or table header."""
    if not text:
        return None
    for pat in _SCALE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0).lower()
    return None


def stitch_cross_page_tables(table_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Reassemble multi-page continuation tables and carry top-level headers & scale footnotes across page boundaries.
    """
    if not table_nodes:
        return []

    stitched: List[Dict[str, Any]] = []
    prev_scale: Optional[str] = None
    prev_headers: Optional[List[str]] = None

    for node in table_nodes:
        node_copy = dict(node)
        raw_markdown = node_copy.get("markdown_content", "") or ""
        parent_text = node_copy.get("parent_section_text", "") or ""

        current_scale = extract_context_scale_from_text(f"{parent_text}\n{raw_markdown}")
        if current_scale:
            prev_scale = current_scale
            node_copy["context_scale"] = current_scale
        elif prev_scale:
            # Carry over previous page's scale footnote
            node_copy["context_scale"] = prev_scale

        # Check if table node is a continuation (e.g. lacks explicit header row but has matching columns)
        extracted = node_copy.get("extracted_data") or {}
        if isinstance(extracted, dict) and "headers" in extracted:
            prev_headers = extracted["headers"]
        elif prev_headers and isinstance(extracted, dict) and "rows" in extracted:
            extracted["headers"] = prev_headers
            node_copy["extracted_data"] = extracted

        stitched.append(node_copy)

    logger.info("Stitched table nodes and carried scale footnotes across pages", node_count=len(stitched))
    return stitched
