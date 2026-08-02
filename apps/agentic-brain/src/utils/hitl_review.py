"""Generate pinpointed HITL reviews in agentic-brain when DLQ escalates."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class CellIssue(BaseModel):
    row_index: int
    column: str
    current_value: Optional[str] = None
    expected_or_issue: str
    suggested_value: Optional[str] = None
    question: str


class HitlReview(BaseModel):
    summary: str
    issues: List[CellIssue] = Field(default_factory=list)
    proposed_extracted_data: Dict[str, Any] = Field(default_factory=dict)


def _heuristic_review(
    critic_error: str,
    extracted_data: Dict[str, Any],
    unmapped_jsonb: Any,
    target_table: str,
) -> HitlReview:
    issues: List[CellIssue] = []
    if critic_error:
        issues.append(
            CellIssue(
                row_index=0,
                column="(verification)",
                current_value=None,
                expected_or_issue=critic_error,
                suggested_value=None,
                question=f"Verification failed: {critic_error}. Approve a corrected extraction?",
            )
        )

    metas = unmapped_jsonb if isinstance(unmapped_jsonb, list) else [unmapped_jsonb] if unmapped_jsonb else []
    for i, meta in enumerate(metas):
        if not isinstance(meta, dict):
            continue
        for col, val in meta.items():
            if col == "critic_error":
                continue
            issues.append(
                CellIssue(
                    row_index=i,
                    column=str(col),
                    current_value=str(val) if val is not None else None,
                    expected_or_issue=f"Unmapped field '{col}'",
                    suggested_value=None,
                    question=f"Row {i}, column '{col}': keep value '{val}' or remap?",
                )
            )

    if not issues:
        issues.append(
            CellIssue(
                row_index=0,
                column="(table)",
                current_value=None,
                expected_or_issue="Max retries exceeded; human review required",
                suggested_value=None,
                question=f"Review extraction for '{target_table}' and approve corrected data?",
            )
        )

    return HitlReview(
        summary=f"DLQ escalation for '{target_table}': {critic_error or 'needs human review'}",
        issues=issues[:50],
        proposed_extracted_data=extracted_data if isinstance(extracted_data, dict) else {},
    )


async def generate_hitl_review_from_dlq(payload: Dict[str, Any], critic_error: str) -> Dict[str, Any]:
    """Use frontier Anthropic LLM when available; otherwise heuristic fallback."""
    if payload.get("hitl_review"):
        return payload["hitl_review"]

    extracted_data = payload.get("extracted_data") or {}
    unmapped = payload.get("unmapped_jsonb") or {}
    target_table = payload.get("target_table") or "unknown"
    fallback = _heuristic_review(critic_error, extracted_data, unmapped, target_table)

    try:
        from llm.factory import LLMFactory, ModelTier
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = LLMFactory.get_llm(ModelTier.FRONTIER)
        schema_hint = HitlReview.model_json_schema()
        prompt = (
            "Return ONLY valid JSON matching this schema:\n"
            f"{json.dumps(schema_hint)}\n\n"
            "Pinpoint issues row-by-row and column-by-column with approve/reject questions.\n"
            f"critic_error: {critic_error}\n"
            f"target_table: {target_table}\n"
            f"extracted_data: {json.dumps(extracted_data, default=str)[:2500]}\n"
            f"unmapped: {json.dumps(unmapped, default=str)[:1500]}"
        )
        messages = [
            SystemMessage(content="You generate precise human-in-the-loop review payloads for document extraction."),
            HumanMessage(content=prompt),
        ]
        response = await llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block) for block in content
            )
        text = str(content).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        parsed = HitlReview.model_validate_json(text)
        if not parsed.proposed_extracted_data:
            parsed.proposed_extracted_data = fallback.proposed_extracted_data
        return parsed.model_dump()
    except Exception as e:
        logger.warning("DLQ HITL LLM review failed, using heuristic", error=str(e))
        return fallback.model_dump()
