"""Financial number parsing and scale-aware comparison."""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

_SCALE_SUFFIX = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
}

_NULLISH = {
    "",
    "-",
    "—",
    "–",
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    ".",
    "…",
}


def parse_scale_multiplier(scale_text: Optional[str]) -> float:
    """Interpret context_scale footnotes like 'in millions', 'USD thousands'."""
    if not scale_text:
        return 1.0
    s = scale_text.strip().lower()
    for key, mult in _SCALE_SUFFIX.items():
        if re.search(rf"\b{re.escape(key)}\b", s):
            return mult
    if "000" in s and "million" not in s:
        return 1_000.0
    return 1.0


def parse_financial_number(value: Any) -> Optional[float]:
    """
    Parse a financial cell into float.
    Handles accounting negatives, currency symbols, percent, and scale suffixes.
    Returns None for blank / dash cells.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    raw = str(value).strip()
    if raw.lower() in _NULLISH:
        return None

    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative = True
        raw = raw[1:-1].strip()
    if raw.startswith("-") or raw.endswith("-"):
        negative = True
        raw = raw.lstrip("-").rstrip("-").strip()
    raw = re.sub(r"[$€£¥₹\s]", "", raw)
    raw = raw.rstrip("%")

    scale = 1.0
    m = re.search(r"(?i)(bn|mm|billion|millions|million|thousand|k|b|m)\s*$", raw)
    if m:
        scale = _SCALE_SUFFIX.get(m.group(1).lower(), 1.0)
        raw = raw[: m.start()].strip()
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        parts = raw.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")

    raw = raw.replace(" ", "")
    if not raw or raw.lower() in _NULLISH:
        return None

    try:
        num = float(raw) * scale
    except ValueError:
        return None

    return -num if negative else num


def scale_from_row(data: dict) -> float:
    """Read context scale multiplier from row (_context_scale_multiplier or context_scale)."""
    if not data:
        return 1.0
    explicit = data.get("_context_scale_multiplier")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return float(explicit)
    return parse_scale_multiplier(data.get("context_scale"))


def effective_tolerance(
    *,
    abs_tol: float = 0.02,
    rel_tol: float = 0.002,
    scale: float = 1.0,
    magnitude: float = 0.0,
) -> float:
    """Widen absolute tolerance with reporting scale and magnitude."""
    scale = scale if scale and scale > 0 else 1.0
    scaled_abs = abs_tol * max(1.0, scale / 1_000.0) if scale >= 1_000 else abs_tol
    return max(scaled_abs, rel_tol * max(abs(magnitude), 1.0))


def nearly_equal(
    a: Optional[float],
    b: Optional[float],
    *,
    abs_tol: float = 0.02,
    rel_tol: float = 0.002,
    scale: float = 1.0,
) -> bool:
    """True if either side missing, or values match within absolute/relative tolerance."""
    if a is None or b is None:
        return True
    tol = effective_tolerance(
        abs_tol=abs_tol, rel_tol=rel_tol, scale=scale, magnitude=max(abs(a), abs(b))
    )
    return abs(a - b) <= tol


def require_equal(
    left: Optional[float],
    right: Optional[float],
    label: str,
    *,
    abs_tol: float = 0.02,
    rel_tol: float = 0.002,
    scale: float = 1.0,
) -> Tuple[bool, str]:
    if left is None or right is None:
        return True, ""
    if nearly_equal(left, right, abs_tol=abs_tol, rel_tol=rel_tol, scale=scale):
        return True, ""
    return False, f"Logic Error: {label} — expected {right}, got {left} (Δ={abs(left - right)})"


def fget(data: dict, *keys: str) -> Optional[float]:
    for k in keys:
        if k in data and data[k] is not None:
            parsed = parse_financial_number(data[k])
            if parsed is not None:
                return parsed
    return None


def present_count(data: dict, *keys: str) -> int:
    return sum(1 for k in keys if fget(data, k) is not None)


def normalize_number_token(value: Any) -> Optional[str]:
    """Canonical string for grounding lookups (strip currency/commas/parens)."""
    parsed = parse_financial_number(value)
    if parsed is None:
        return None
    if abs(parsed - round(parsed)) < 1e-9:
        return str(int(round(parsed)))
    return f"{parsed:.4f}".rstrip("0").rstrip(".")


def value_grounded_in_source(value: Any, source_text: str, *, scale: float = 1.0) -> bool:
    """
    True if the numeric appears in source text (raw or scaled), or source is empty.
    Empty source skips grounding (caller may not have markdown).
    """
    if not source_text or not str(source_text).strip():
        return True
    token = normalize_number_token(value)
    if token is None:
        return True
    blob = str(source_text)
    compact = re.sub(r"[, \u00a0]", "", blob)
    if token in compact or token in blob:
        return True
    parsed = parse_financial_number(value)
    if parsed is None:
        return True
    candidates = {token, f"{parsed:,.2f}", f"{parsed:,.0f}", f"({abs(parsed):,.2f})" if parsed < 0 else ""}
    if scale and scale != 1.0:
        scaled = parsed  # row values are typically already in footnote units
        candidates.add(normalize_number_token(scaled) or "")
    for c in candidates:
        if c and (c in blob or c.replace(",", "") in compact):
            return True
    return False
