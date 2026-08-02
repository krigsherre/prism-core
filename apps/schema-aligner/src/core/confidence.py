"""Confidence scoring and promotion bands."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.critic_types import CriticResult, Severity


class PromotionBand(str, Enum):
    AUTO_PROMOTE = "auto_promote"
    REVIEW = "review"
    REJECT = "reject"


@dataclass
class ConfidenceReport:
    score: float
    band: PromotionBand
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence_score": round(self.score, 4),
            "promotion_band": self.band.value,
            "confidence_reasons": list(self.reasons),
        }


def compute_confidence(
    *,
    critic_results: List[CriticResult],
    structure: Optional[Dict[str, Any]] = None,
    drift_ratio: float = 0.0,
    grounding_misses: int = 0,
    grounding_checked: int = 0,
    auto_promote_min: float = 0.85,
    review_min: float = 0.55,
) -> ConfidenceReport:
    score = 1.0
    reasons: List[str] = []

    hard = [r for r in critic_results if not r.ok and r.severity == Severity.HARD]
    soft = [r for r in critic_results if not r.ok and r.severity == Severity.SOFT]

    if hard:
        return ConfidenceReport(
            score=0.0,
            band=PromotionBand.REJECT,
            reasons=[f"hard_critic:{hard[0].rule_id}"],
        )

    for r in soft:
        score -= 0.12
        reasons.append(f"soft_critic:{r.rule_id}")

    if structure and structure.get("ok") is False:
        score -= 0.35
        reasons.append("structure_fail")
    elif structure:
        empty_ratio = float((structure.get("stats") or {}).get("empty_cell_ratio") or 0.0)
        if empty_ratio > 0.4:
            score -= 0.1
            reasons.append("sparse_table")

    if drift_ratio > 0.3:
        score -= min(0.25, drift_ratio * 0.5)
        reasons.append(f"drift_ratio:{drift_ratio:.2f}")

    if grounding_checked > 0:
        miss_rate = grounding_misses / grounding_checked
        if miss_rate > 0:
            score -= min(0.3, miss_rate * 0.4)
            reasons.append(f"grounding_miss_rate:{miss_rate:.2f}")

    score = max(0.0, min(1.0, score))

    if score >= auto_promote_min and not soft:
        band = PromotionBand.AUTO_PROMOTE
    elif score >= review_min:
        band = PromotionBand.REVIEW
        if not reasons:
            reasons.append("below_auto_promote_threshold")
    else:
        band = PromotionBand.REJECT
        reasons.append("below_review_threshold")

    if soft and band == PromotionBand.AUTO_PROMOTE:
        band = PromotionBand.REVIEW

    return ConfidenceReport(score=score, band=band, reasons=reasons)


def band_to_status(band: PromotionBand) -> str:
    if band == PromotionBand.AUTO_PROMOTE:
        return "MAPPED"
    if band == PromotionBand.REVIEW:
        return "NEEDS_REVIEW"
    return "FAILED_VERIFICATION"
