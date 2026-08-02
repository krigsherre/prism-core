"""Structured critic results."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    INFO = "info"


@dataclass
class CriticResult:
    ok: bool
    rule_id: str = ""
    severity: Severity = Severity.HARD
    message: str = ""
    fields: List[str] = field(default_factory=list)
    expected: Optional[float] = None
    actual: Optional[float] = None
    delta: Optional[float] = None
    actionable_hint: str = ""

    def as_error_string(self) -> str:
        if self.ok:
            return ""
        parts = []
        if self.rule_id:
            parts.append(f"[{self.rule_id}]")
        if self.message:
            parts.append(self.message)
        elif self.expected is not None and self.actual is not None:
            parts.append(
                f"Logic Error: expected {self.expected}, got {self.actual}"
                f" (Δ={abs(self.actual - self.expected)})"
            )
        if self.actionable_hint:
            parts.append(f"Hint: {self.actionable_hint}")
        return " ".join(parts) if parts else "Logic Error: critic failed"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value if isinstance(self.severity, Severity) else self.severity
        return d

    @staticmethod
    def pass_() -> "CriticResult":
        return CriticResult(ok=True)

    @staticmethod
    def fail(
        rule_id: str,
        message: str,
        *,
        fields: Optional[List[str]] = None,
        expected: Optional[float] = None,
        actual: Optional[float] = None,
        severity: Severity = Severity.HARD,
        actionable_hint: str = "",
    ) -> "CriticResult":
        delta = None
        if expected is not None and actual is not None:
            delta = abs(actual - expected)
        return CriticResult(
            ok=False,
            rule_id=rule_id,
            severity=severity,
            message=message,
            fields=list(fields or []),
            expected=expected,
            actual=actual,
            delta=delta,
            actionable_hint=actionable_hint,
        )


def merge_results(results: List[CriticResult]) -> CriticResult:
    soft: Optional[CriticResult] = None
    for r in results:
        if r.ok:
            continue
        if r.severity == Severity.HARD:
            return r
        if soft is None and r.severity == Severity.SOFT:
            soft = r
    return soft if soft is not None else CriticResult.pass_()


def results_to_meta(results: List[CriticResult]) -> Dict[str, Any]:
    failures = [r.to_dict() for r in results if not r.ok]
    hard = [r for r in results if not r.ok and r.severity == Severity.HARD]
    soft = [r for r in results if not r.ok and r.severity == Severity.SOFT]
    return {
        "critic_version": "v3",
        "critic_results": failures,
        "hard_failures": [r.rule_id for r in hard],
        "soft_failures": [r.rule_id for r in soft],
        "critic_error": merge_results(results).as_error_string(),
    }
