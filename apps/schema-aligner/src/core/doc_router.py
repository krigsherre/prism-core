"""Deterministic schema router before LLM classification."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

_RULES: List[Tuple[str, float, Tuple[str, ...]]] = [
    (
        "standardized_balance_sheet",
        1.0,
        (
            r"balance\s*sheet",
            r"statement of financial position",
            r"total\s+assets",
            r"shareholders[\'’]?\s+equity",
            r"liabilities\s+and\s+equity",
        ),
    ),
    (
        "standardized_income_statement",
        1.0,
        (
            r"income\s+statement",
            r"profit\s+and\s+loss",
            r"\bp\s*&\s*l\b",
            r"statement of operations",
            r"net\s+income",
            r"cost of (goods|sales)",
            r"\bebitda\b",
        ),
    ),
    (
        "standardized_cash_flow",
        1.0,
        (
            r"cash\s+flow",
            r"operating activities",
            r"investing activities",
            r"financing activities",
            r"net change in cash",
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
