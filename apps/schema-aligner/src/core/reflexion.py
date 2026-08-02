"""Critic-guided Reflexion: classify failures and build repair prompts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FailureClass(str, Enum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


_PERMANENT_PATTERNS = (
    r"no critic registered",
    r"critic\.missing_",
    r"empty extracted",
    r"unsupported schema",
    r"unknown_table",
    r"could not classify",
    r"no table detected",
    r"file not found",
    r"ocr returned empty",
    r"missing page",
)

_RETRYABLE_PATTERNS = (
    r"logic error",
    r"\[bs\.",
    r"\[is\.",
    r"\[cf\.",
    r"\[bank\.",
    r"\[inv\.",
    r"\[po\.",
    r"\[receipt\.",
    r"\[grounding\.",
    r"completeness",
    r"total_assets",
    r"gross_profit",
    r"net_change_in_cash",
    r"closing",
    r"running balance",
    r"line total",
    r"amount_due",
    r"does not match",
    r"exceeds",
    r"incomplete extraction",
    r"Δ=",
    r"hint:",
)


@dataclass
class ReflexionAttempt:
    attempt: int
    tier: str  # "repair" | "focused_repair" | "escalated_repair"
    critic_error: str = ""
    status: str = ""


@dataclass
class ReflexionState:
    attempts: List[ReflexionAttempt] = field(default_factory=list)
    last_error: str = ""
    failure_class: FailureClass = FailureClass.UNKNOWN

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def classify_failure(error: str, *, status: str = "", target_table: str = "") -> FailureClass:
    blob = f"{error} {status} {target_table}".lower()
    if not error and status in ("FAILED", "NEEDS_REVIEW") and not target_table:
        return FailureClass.PERMANENT
    if status == "FAILED" and not error:
        return FailureClass.PERMANENT
    for pat in _PERMANENT_PATTERNS:
        if re.search(pat, blob):
            return FailureClass.PERMANENT
    for pat in _RETRYABLE_PATTERNS:
        if re.search(pat, blob):
            return FailureClass.RETRYABLE
    if "logic error" in blob or status == "FAILED_VERIFICATION":
        return FailureClass.RETRYABLE
    if status in ("FAILED",) or target_table in ("", "UNKNOWN_TABLE"):
        return FailureClass.PERMANENT
    return FailureClass.UNKNOWN


def tier_for_attempt(attempt_index: int) -> str:
    """0-based attempt index → repair tier."""
    if attempt_index <= 0:
        return "initial"
    if attempt_index == 1:
        return "repair"
    if attempt_index == 2:
        return "focused_repair"
    return "escalated_repair"


def format_few_shot_block(examples: Optional[List[Dict[str, Any]]]) -> str:
    """Prompt fragment from prior HITL corrections (same schema)."""
    if not examples:
        return ""
    import json

    lines = ["- FEW-SHOT FROM PRIOR HITL CORRECTIONS (same schema):"]
    for i, ex in enumerate(examples, start=1):
        patches = ex.get("field_patches") or []
        critic = ex.get("critic_error") or ""
        after = ex.get("after_data")
        lines.append(f"  Example {i}: critic was '{critic}'")
        if patches:
            for p in patches[:8]:
                if not isinstance(p, dict):
                    continue
                lines.append(
                    f"    {p.get('column')}: {p.get('before')!r} → {p.get('after')!r}"
                )
        elif after:
            preview = after[0] if isinstance(after, list) and after else after
            lines.append(f"    corrected row: {json.dumps(preview, default=str)[:400]}")
    lines.append("- Apply the same correction pattern when the critic error is similar.")
    return "\n".join(lines) + "\n"


def build_repair_instructions(
    *,
    critic_error: str,
    previous_rows: Optional[List[Dict[str, Any]]],
    attempt_index: int,
    target_table: str,
    few_shot_examples: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Prompt fragment injected on retry attempts."""
    tier = tier_for_attempt(attempt_index)
    prev_preview = ""
    if previous_rows:
        import json

        prev_preview = json.dumps(previous_rows[:2], ensure_ascii=False, default=str)[:1500]

    lines = [
        "REFLEXION REPAIR MODE:",
        f"- Attempt tier: {tier} (attempt {attempt_index + 1}).",
        f"- Target schema: {target_table}.",
        f"- Critic rejected the previous extraction with: {critic_error}",
        "- Fix ONLY the fields implicated by the critic. Do not invent new totals.",
        "- Re-read the Target Chunk carefully; prefer source digits over prior output.",
        "- If the critic cites a rule_id in [brackets], treat that identity as mandatory.",
    ]
    if tier == "focused_repair":
        lines.append(
            "- FOCUSED: output corrected values for failing accounting identities; "
            "leave unrelated fields unchanged from the previous extraction when possible."
        )
    if tier == "escalated_repair":
        lines.append(
            "- ESCALATED: be conservative — if a figure is illegible, set it null rather than guess. "
            "Ensure accounting identities hold exactly."
        )
    few = format_few_shot_block(few_shot_examples)
    if few:
        lines.append(few.rstrip())
    if prev_preview:
        lines.append(f"- Previous extraction (to correct):\n{prev_preview}")
    return "\n".join(lines) + "\n"


def extract_critic_errors(unmapped: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    for meta in unmapped or []:
        if isinstance(meta, dict) and meta.get("critic_error"):
            errors.append(str(meta["critic_error"]))
    return errors


def merge_critic_error(unmapped: List[Dict[str, Any]]) -> str:
    errs = extract_critic_errors(unmapped)
    return "; ".join(errs) if errs else ""
