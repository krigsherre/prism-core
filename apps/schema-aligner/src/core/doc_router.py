"""Deterministic schema router before LLM classification."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

_RULES: List[Tuple[str, float, Tuple[str, ...]]] = [
    (
        "standardized_balance_sheet",
        1.0,
        (
            r"balance\s*sheets?",
            r"statement\s+of\s+financial\s+position",
            r"consolidated\s+balance\s+sheets?",
            r"total\s+assets",
            r"shareholders[\'’]?\s+equity",
            r"stockholders[\'’]?\s+equity",
            r"liabilities\s+and\s+equity",
            r"current\s+assets",
            r"current\s+liabilities",
        ),
    ),
    (
        "standardized_income_statement",
        1.0,
        (
            r"income\s+statements?",
            r"profit\s+and\s+loss",
            r"\bp\s*&\s*l\b",
            r"statement\s+of\s+operations",
            r"consolidated\s+statements?\s+of\s+(operations|income|earnings|comprehensive\s+income)",
            r"net\s+income",
            r"net\s+sales",
            r"revenue\s+from\s+operations",
            r"total\s+revenues?",
            r"cost of (goods|sales|revenue)",
            r"\bebitda\b",
        ),
    ),
    (
        "standardized_cash_flow",
        1.0,
        (
            r"cash\s+flows?",
            r"consolidated\s+statements?\s+of\s+cash\s+flows?",
            r"operating activities",
            r"investing activities",
            r"financing activities",
            r"net change in cash",
        ),
    ),
    (
        "corporate_subsidiaries",
        0.95,
        (
            r"subsidiaries\s+of\s+the\s+registrant",
            r"exhibit\s+21",
            r"jurisdiction\s+of\s+incorporation",
            r"percentage\s+of\s+ownership",
            r"name\s+of\s+subsidiary",
            r"subsidiary\s+company",
            r"holding\s+company",
            r"basis\s+of\s+consolidation",
        ),
    ),
    (
        "sec_10k_footnote_schedule",
        0.85,
        (
            r"note\s+\d+",
            r"segment\s+reporting",
            r"disaggregated\s+revenue",
            r"lease\s+commitments?",
            r"debt\s+maturities",
        ),
    ),
    (
        "bank_statement_transactions",
        0.95,
        (
            r"bank\s+statement",
            r"opening balance",
            r"closing balance",
            r"withdrawal",
            r"deposit",
            r"running balance",
        ),
    ),
    (
        "bank_statement_headers",
        0.9,
        (r"account number", r"statement period", r"beginning balance", r"ending balance"),
    ),
    (
        "vendor_invoice_headers",
        0.95,
        (r"\binvoice\b", r"bill to", r"invoice number", r"amount due", r"subtotal"),
    ),
    (
        "invoice_line_items",
        0.85,
        (r"unit price", r"quantity", r"line total", r"description of (goods|services)"),
    ),
    (
        "purchase_order_headers",
        0.9,
        (r"purchase\s+order", r"\bpo\s*#", r"\bpo number"),
    ),
    (
        "receipt_headers",
        0.85,
        (r"\breceipt\b", r"merchant", r"thank you for your (purchase|business)"),
    ),
    (
        "tax_form_headers",
        0.9,
        (r"\bw-?2\b", r"form 1040", r"adjusted gross income", r"medicare wages"),
    ),
    (
        "utility_bills",
        0.85,
        (r"utility", r"kwh", r"meter reading", r"amount due"),
    ),
]


def route_document(
    text: str,
    *,
    allowed_schemas: Optional[List[str]] = None,
    min_score: float = 1.5,
) -> Tuple[str, float, Dict[str, float]]:
    blob = (text or "").lower()
    if not blob.strip():
        return "", 0.0, {}

    allowed = set(allowed_schemas) if allowed_schemas else None
    scores: Dict[str, float] = {}
    for schema, weight, patterns in _RULES:
        if allowed is not None and schema not in allowed:
            continue
        hits = sum(1.0 for pat in patterns if re.search(pat, blob, re.IGNORECASE))
        if hits:
            scores[schema] = hits * weight

    if not scores:
        return "", 0.0, {}

    best_schema, best_score = max(scores.items(), key=lambda kv: kv[1])
    ranked = sorted(scores.values(), reverse=True)
    if best_score < min_score:
        return "", best_score, scores
    if len(ranked) > 1 and ranked[0] < ranked[1] + 0.75:
        return "", best_score, scores
    return best_schema, best_score, scores


def detect_jurisdiction(text: str) -> str:
    """Detect whether a document is an Indian Annual Report (IND) vs SEC 10-K (US) vs Global."""
    blob = (text or "").lower()
    if not blob.strip():
        return "GLOBAL"

    indian_patterns = [
        r"companies\s+act",
        r"ind\s+as",
        r"schedule\s+iii",
        r"sebi",
        r"bse\s+limited",
        r"national\s+stock\s+exchange",
        r"\bcin\b",
        r"crores?",
        r"lakhs?",
        r"₹",
        r"rs\.",
        r"standalone\s+financial",
    ]
    us_patterns = [
        r"form\s+10-?k",
        r"securities\s+and\s+exchange\s+commission",
        r"commission\s+file\s+number",
        r"us-gaap",
        r"item\s+8\.",
    ]

    indian_score = sum(1.0 for pat in indian_patterns if re.search(pat, blob, re.IGNORECASE))
    us_score = sum(1.0 for pat in us_patterns if re.search(pat, blob, re.IGNORECASE))

    if indian_score > us_score and indian_score >= 1.0:
        return "IND"
    elif us_score > indian_score and us_score >= 1.0:
        return "US"
    return "GLOBAL"


def extract_entity_identifiers(text: str) -> Dict[str, Optional[str]]:
    """
    Extract regulatory entity identifiers:
    - CIN (Indian Corporate Identity Number: L17110MH1973PLC019786)
    - CIK (US SEC Central Index Key: 0000320193)
    - Ticker (US stock ticker: AAPL)
    - NSE Symbol (Indian stock exchange symbol: RELIANCE)
    """
    if not text:
        return {"cin": None, "cik": None, "ticker": None, "nse_symbol": None}

    cin_m = re.search(r"\b([LU]\d{5}[A-Z]{2}\d{4}PLC\d{6})\b", text, re.IGNORECASE)
    cik_m = re.search(r"\bCIK[:\s]*(\d{6,10})\b", text, re.IGNORECASE)
    ticker_m = re.search(r"\bTicker[:\s]*([A-Z]{1,5})\b", text)
    nse_m = re.search(r"\bNSE[:\s]*([A-Z0-9_-]{2,15})\b", text, re.IGNORECASE)

    return {
        "cin": cin_m.group(1).upper() if cin_m else None,
        "cik": cik_m.group(1) if cik_m else None,
        "ticker": ticker_m.group(1).upper() if ticker_m else None,
        "nse_symbol": nse_m.group(1).upper() if nse_m else None,
    }


