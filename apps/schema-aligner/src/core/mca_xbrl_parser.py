"""Indian MCA (Ministry of Corporate Affairs) / Ind AS XBRL XML Parser."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)


def is_mca_xbrl_content(text: str) -> bool:
    """True if text contains Indian MCA / Ind AS XBRL XML tags."""
    if not text:
        return False
    return "ind-as:" in text or "in-gaap:" in text or "xmlns:in-gaap=" in text or "mca.gov.in" in text


def parse_mca_xbrl_facts(xml_content: str) -> Dict[str, Any]:
    """
    Extract facts directly from MCA / Ind AS XML elements.
    Returns normalized line items (e.g. RevenueFromOperations, ProfitLossForPeriod).
    """
    if not xml_content:
        return {}

    facts: Dict[str, Any] = {}

    # Extract ind-as: or in-gaap: XML element values
    pattern = r'<(?:ind-as|in-gaap):([a-zA-Z0-9_-]+)\s*[^>]*>(.*?)</(?:ind-as|in-gaap):[a-zA-Z0-9_-]+>'
    matches = re.findall(pattern, xml_content, re.IGNORECASE | re.DOTALL)
    for concept, raw_val in matches:
        clean_concept = str(concept).strip()
        val_text = re.sub(r'<[^>]+>', '', raw_val).strip()
        if clean_concept and val_text and clean_concept not in facts:
            facts[clean_concept] = val_text

    logger.info("Parsed MCA Ind AS XBRL facts directly from XML", fact_count=len(facts))
    return facts
