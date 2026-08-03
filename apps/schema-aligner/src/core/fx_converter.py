"""Multi-Currency FX Conversion Engine."""
from __future__ import annotations

from typing import Dict, Optional
import structlog

logger = structlog.get_logger(__name__)

_FX_RATES_TO_USD: Dict[str, float] = {
    "USD": 1.0,
    "INR": 83.50,
    "EUR": 0.92,
    "GBP": 0.78,
    "JPY": 155.0,
    "CAD": 1.36,
    "AUD": 1.50,
}


def get_fx_rate(from_currency: str, to_currency: str) -> float:
    """Calculate cross rate from_currency -> to_currency."""
    src = (from_currency or "USD").strip().upper()
    dst = (to_currency or "USD").strip().upper()

    if src == dst:
        return 1.0

    src_rate = _FX_RATES_TO_USD.get(src, 1.0)
    dst_rate = _FX_RATES_TO_USD.get(dst, 1.0)

    cross_rate = dst_rate / src_rate
    return float(cross_rate)


def convert_currency(
    amount: Optional[float],
    from_currency: str,
    to_currency: str = "USD",
) -> Optional[float]:
    """Convert amount from from_currency to to_currency."""
    if amount is None:
        return None

    rate = get_fx_rate(from_currency, to_currency)
    converted = amount * rate
    logger.debug("Converted currency", amount=amount, src=from_currency, dst=to_currency, rate=rate)
    return round(converted, 2)
