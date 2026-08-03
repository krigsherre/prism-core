"""SEC EDGAR Inline XBRL (iXBRL) Fast-Path Parser."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)


def is_ixbrl_content(text: str) -> bool:
    """True if text contains SEC EDGAR inline XBRL tags."""
    if not text:
        return False
    return "ix:nonFraction" in text or "ix:nonNumeric" in text or "xmlns:ix=" in text


def parse_ixbrl_facts(html_content: str) -> Dict[str, Any]:
    """
    Extract facts directly from iXBRL tags (<ix:nonFraction>, <ix:nonNumeric>).
    Returns a dictionary of normalized line items and context metadata.
    """
    if not html_content:
        return {}

    facts: Dict[str, Any] = {}
    contexts: Dict[str, str] = {}

    # Extract nonFraction tags (numeric financial values)
    pattern = r'<ix:nonFraction\s+[^>]*name=["\'](?:[a-zA-Z0-9_-]+:)?([a-zA-Z0-9_-]+)["\'][^>]*>(.*?)</ix:nonFraction>'
    matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
    for concept, raw_val in matches:
        clean_concept = str(concept).strip()
        val_text = re.sub(r'<[^>]+>', '', raw_val).strip()
        if clean_concept and val_text:
            facts[clean_concept] = val_text

    # Extract nonNumeric tags (text disclosures / context notes)
    non_num_pattern = r'<ix:nonNumeric\s+[^>]*name=["\'](?:[a-zA-Z0-9_-]+:)?([a-zA-Z0-9_-]+)["\'][^>]*>(.*?)</ix:nonNumeric>'
    non_num_matches = re.findall(non_num_pattern, html_content, re.IGNORECASE | re.DOTALL)
    for concept, raw_val in non_num_matches:
        clean_concept = str(concept).strip()
        val_text = re.sub(r'<[^>]+>', '', raw_val).strip()
        if clean_concept and val_text and clean_concept not in facts:
            facts[clean_concept] = val_text[:500]  # truncate long disclosures

    logger.info("Parsed iXBRL facts directly from HTML", fact_count=len(facts))
    return facts
