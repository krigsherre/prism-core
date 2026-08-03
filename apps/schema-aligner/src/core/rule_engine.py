"""Declarative critic rule packs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from core.critic_types import CriticResult, Severity
from core.financial_numerics import fget, nearly_equal, present_count, scale_from_row

logger = structlog.get_logger(__name__)

Row = Dict[str, Any]


@dataclass
class PackRule:
    id: str
    type: str  # completeness | sum_equals | diff_equals | product_equals | bounds | mutex_positive
    severity: Severity = Severity.HARD
    require: List[str] = field(default_factory=list)
    trigger_any_of: List[str] = field(default_factory=list)
    left: str = ""
    right: List[str] = field(default_factory=list) 
    op: str = "add"  # add | sub | mul
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    fields: List[str] = field(default_factory=list)
    skip_if_any_present: List[str] = field(default_factory=list)
    hint: str = ""
    message: str = ""


@dataclass
class DomainPack:
    name: str
    schemas: List[str]
    rules: Dict[str, List[PackRule]]  # schema -> rules
    grounding_fields: Dict[str, List[str]] = field(default_factory=dict)
    aliases: Dict[str, str] = field(default_factory=dict)


def _severity(raw: str) -> Severity:
    s = (raw or "hard").strip().lower()
    if s == "soft":
        return Severity.SOFT
    if s == "info":
        return Severity.INFO
    return Severity.HARD


def _parse_rule(raw: Dict[str, Any]) -> PackRule:
    right = raw.get("right") or []
    if isinstance(right, str):
        right = [right]
    return PackRule(
        id=str(raw.get("id") or "pack.unnamed"),
        type=str(raw.get("type") or "sum_equals"),
        severity=_severity(str(raw.get("severity") or "hard")),
        require=list(raw.get("require") or []),
        trigger_any_of=list(raw.get("trigger_any_of") or []),
        left=str(raw.get("left") or ""),
        right=[str(x) for x in right],
        op=str(raw.get("op") or "add"),
        min_value=raw.get("min_value"),
        max_value=raw.get("max_value"),
        fields=list(raw.get("fields") or []),
        skip_if_any_present=list(raw.get("skip_if_any_present") or []),
        hint=str(raw.get("hint") or ""),
        message=str(raw.get("message") or ""),
    )


def load_packs(packs_dir: Optional[str] = None) -> List[DomainPack]:
    base = packs_dir or os.path.join(os.path.dirname(__file__), "packs")
    if not os.path.isdir(base):
        return []
    packs: List[DomainPack] = []
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        critics_path = os.path.join(path, "critics.json")
        if not os.path.exists(critics_path):
            continue
        try:
            with open(critics_path, "r") as f:
                raw = json.load(f)
        except Exception as e:
            logger.warning("Failed to load domain pack", pack=name, error=str(e))
            continue

        rules: Dict[str, List[PackRule]] = {}
        for schema, rule_list in (raw.get("rules") or {}).items():
            rules[schema] = [_parse_rule(r) for r in rule_list if isinstance(r, dict)]

        aliases: Dict[str, str] = {}
        aliases_path = os.path.join(path, "aliases.json")
        if os.path.exists(aliases_path):
            try:
                with open(aliases_path, "r") as f:
                    aliases = {str(k).strip().lower(): str(v) for k, v in json.load(f).items()}
            except Exception:
                aliases = {}

        packs.append(
            DomainPack(
                name=name,
                schemas=list(raw.get("schemas") or rules.keys()),
                rules=rules,
                grounding_fields={
                    k: list(v) for k, v in (raw.get("grounding_fields") or {}).items()
                },
                aliases=aliases,
            )
        )
        logger.info("Loaded domain pack", pack=name, schemas=len(rules), rules=sum(len(v) for v in rules.values()))
    return packs


def eval_rule(rule: PackRule, data: Row) -> Optional[CriticResult]:
    if rule.skip_if_any_present and present_count(data, *rule.skip_if_any_present) > 0:
        return None
    scale = scale_from_row(data)
    rtype = rule.type

    if rtype == "completeness":
        triggers = rule.trigger_any_of or rule.require
        if present_count(data, *triggers) == 0:
            return None
        missing = [k for k in rule.require if fget(data, k) is None]
        if not missing:
            return None
        return CriticResult.fail(
            rule.id,
            rule.message
            or f"Logic Error: incomplete extraction — missing {missing}",
            fields=rule.require,
            severity=rule.severity,
            actionable_hint=rule.hint
            or f"Populate missing fields {missing} from the source table.",
        )

    if rtype in ("sum_equals", "diff_equals", "product_equals"):
        left = fget(data, rule.left) if rule.left else None
        rights = [fget(data, k) for k in rule.right]
        if left is None or any(v is None for v in rights):
            return None
        if rule.op == "sub" or rtype == "diff_equals":
            expected = rights[0]
            for v in rights[1:]:
                expected = expected - (v or 0)  # type: ignore[operator]
        elif rule.op == "mul" or rtype == "product_equals":
            expected = 1.0
            for v in rights:
                expected *= v or 0
        else:
            expected = sum(v or 0 for v in rights)
        if nearly_equal(left, expected, scale=scale):
            return None
        return CriticResult.fail(
            rule.id,
            rule.message
            or f"Logic Error: {rule.left} ≠ {rule.op}({', '.join(rule.right)}) — expected {expected}, got {left}",
            fields=[rule.left, *rule.right],
            expected=float(expected),
            actual=float(left),
            severity=rule.severity,
            actionable_hint=rule.hint
            or f"Re-extract {rule.left} and {', '.join(rule.right)} so the identity holds.",
        )

    if rtype == "bounds":
        for key in rule.fields or ([rule.left] if rule.left else []):
            val = fget(data, key)
            if val is None:
                continue
            if rule.min_value is not None and val < rule.min_value:
                return CriticResult.fail(
                    rule.id,
                    rule.message or f"Logic Error: {key}={val} below min {rule.min_value}",
                    fields=[key],
                    actual=val,
                    severity=rule.severity,
                    actionable_hint=rule.hint,
                )
            if rule.max_value is not None and val > rule.max_value:
                return CriticResult.fail(
                    rule.id,
                    rule.message or f"Logic Error: {key}={val} above max {rule.max_value}",
                    fields=[key],
                    actual=val,
                    severity=rule.severity,
                    actionable_hint=rule.hint,
                )
        return None

    if rtype == "mutex_positive":
        vals = [(k, fget(data, k)) for k in rule.fields]
        positive = [k for k, v in vals if v is not None and v > 0]
        if len(positive) > 1:
            return CriticResult.fail(
                rule.id,
                rule.message or f"Logic Error: mutually exclusive positives: {positive}",
                fields=rule.fields,
                severity=rule.severity,
                actionable_hint=rule.hint,
            )
        return None

    logger.warning("Unknown pack rule type", rule_id=rule.id, type=rtype)
    return None


def eval_pack_rules(rules: List[PackRule], data: Row) -> List[CriticResult]:
    out: List[CriticResult] = []
    for rule in rules:
        result = eval_rule(rule, data)
        if result is not None:
            out.append(result)
            if result.severity == Severity.HARD and rule.type == "completeness":
                return out
    return out
