"""Generate pinpointed HITL review prompts via Anthropic (instructor)."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx
import instructor
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
MODEL_NAME = os.environ.get("LLM_MODEL", os.environ.get("HITL_LLM_MODEL", "claude-haiku-4-5-20251001"))


class CellIssue(BaseModel):
    row_index: int = Field(..., description="0-based row index in the extracted table")
    column: str = Field(..., description="Target schema column or raw header name")
    current_value: Optional[str] = Field(None, description="Value currently extracted")
    expected_or_issue: str = Field(..., description="What is wrong or what is expected")
    suggested_value: Optional[str] = Field(None, description="Suggested corrected value if known")
    question: str = Field(..., description="Clear approve/reject question for the human reviewer")


class HitlReview(BaseModel):
    summary: str = Field(..., description="One-paragraph summary of what the human must decide")
    issues: List[CellIssue] = Field(default_factory=list, description="Pinpointed cell-level issues")
    proposed_extracted_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Corrected extracted_data the human can approve as-is or edit",
    )


def _build_llm_client():
    if LLM_PROVIDER == "anthropic":
        return instructor.from_anthropic(
            AsyncAnthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                http_client=httpx.AsyncClient(
                    limits=httpx.Limits(max_connections=50, max_keepalive_connections=10)
                ),
            )
        )
    openai_base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("VLLM_API_BASE")
        or "http://vllm-server:8002"
    )
    openai_api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLLM_API_KEY") or "EMPTY"

    return AsyncOpenAI(
        base_url=openai_base_url,
        api_key=openai_api_key,
        http_client=httpx.AsyncClient(
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10)
        ),
    )


_llm_client = None


def _client():
    global _llm_client
    if _llm_client is None:
        _llm_client = _build_llm_client()
    return _llm_client


def _heuristic_fallback(
    target_table: str,
    strict_columns: List[Dict[str, Any]],
    unmapped_jsonb: List[Dict[str, Any]],
    drifted_columns: List[str],
    critic_errors: List[str],
    extracted_data: Dict[str, Any],
) -> HitlReview:
    """Deterministic fallback when the LLM is unavailable."""
    issues: List[CellIssue] = []
    for i, meta in enumerate(unmapped_jsonb or []):
        if not isinstance(meta, dict):
            continue
        critic = meta.get("critic_error")
        if critic:
            issues.append(
                CellIssue(
                    row_index=i,
                    column="(row)",
                    current_value=json.dumps(strict_columns[i]) if i < len(strict_columns) else None,
                    expected_or_issue=str(critic),
                    suggested_value=None,
                    question=f"Row {i}: verification failed — {critic}. Approve a corrected row?",
                )
            )
        for col, val in meta.items():
            if col == "critic_error":
                continue
            issues.append(
                CellIssue(
                    row_index=i,
                    column=str(col),
                    current_value=str(val) if val is not None else None,
                    expected_or_issue=f"Unmapped / drifted column '{col}' on table '{target_table}'",
                    suggested_value=None,
                    question=f"Row {i}, column '{col}': map value '{val}' to a schema column, or discard?",
                )
            )

    for col in drifted_columns or []:
        if any(iss.column == col for iss in issues):
            continue
        issues.append(
            CellIssue(
                row_index=0,
                column=str(col),
                current_value=None,
                expected_or_issue=f"Column '{col}' does not match registered schema for '{target_table}'",
                suggested_value=None,
                question=f"Approve adding synonym/mapping for drifted column '{col}' on '{target_table}'?",
            )
        )

    for err in critic_errors or []:
        if not err:
            continue
        if any(err in iss.expected_or_issue for iss in issues):
            continue
        issues.append(
            CellIssue(
                row_index=0,
                column="(verification)",
                current_value=None,
                expected_or_issue=err,
                suggested_value=None,
                question=f"Verification error: {err}. Approve corrected extracted data?",
            )
        )

    if not issues:
        issues.append(
            CellIssue(
                row_index=0,
                column="(table)",
                current_value=None,
                expected_or_issue="Schema alignment needs human review",
                suggested_value=None,
                question=f"Review mapping for table '{target_table}' and approve or reject?",
            )
        )

    summary_parts = [f"HITL review for '{target_table}' with {len(issues)} cell-level issue(s)."]
    if drifted_columns:
        summary_parts.append(f"Drifted columns: {', '.join(drifted_columns)}.")
    if critic_errors:
        summary_parts.append(f"Critic: {critic_errors[0]}")

    proposed = extracted_data or {}
    if strict_columns and not proposed:
        proposed = {"rows": strict_columns}

    return HitlReview(
        summary=" ".join(summary_parts),
        issues=issues[:50],
        proposed_extracted_data=proposed if isinstance(proposed, dict) else {},
    )


async def generate_hitl_review(
    target_table: str,
    strict_columns: Optional[List[Dict[str, Any]]] = None,
    unmapped_jsonb: Optional[List[Dict[str, Any]]] = None,
    drifted_columns: Optional[List[str]] = None,
    critic_errors: Optional[List[str]] = None,
    extracted_data: Optional[Dict[str, Any]] = None,
    source_headers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Call Anthropic to produce a pinpointed HITL review.
    Always returns a dict suitable for Kafka/DB JSON payloads.
    """
    strict_columns = strict_columns if isinstance(strict_columns, list) else ([strict_columns] if strict_columns else [])
    unmapped_jsonb = unmapped_jsonb if isinstance(unmapped_jsonb, list) else ([unmapped_jsonb] if unmapped_jsonb else [])
    drifted_columns = list(drifted_columns or [])
    critic_errors = list(critic_errors or [])
    extracted_data = extracted_data if isinstance(extracted_data, dict) else {}
    source_headers = source_headers or list(extracted_data.keys())

    # Collect critic errors from unmapped metas
    for meta in unmapped_jsonb:
        if isinstance(meta, dict) and meta.get("critic_error"):
            critic_errors.append(str(meta["critic_error"]))

    fallback = _heuristic_fallback(
        target_table, strict_columns, unmapped_jsonb, drifted_columns, critic_errors, extracted_data
    )

    context = {
        "target_table": target_table,
        "source_headers": source_headers,
        "drifted_columns": drifted_columns,
        "critic_errors": critic_errors,
        "strict_columns_sample": strict_columns[:5],
        "unmapped_sample": unmapped_jsonb[:5],
        "extracted_data_preview": json.dumps(extracted_data, default=str)[:3000],
    }

    sys_prompt = (
        "You are a data-quality reviewer for financial document extraction. "
        "Produce a precise human-in-the-loop review that pinpoints issues ROW BY ROW and COLUMN BY COLUMN. "
        "Each issue must ask a clear approve/reject question. "
        "Fill proposed_extracted_data with the best corrected structure for one-click approval "
        "(columnar dict of arrays or list of row objects). "
        "Do not invent columns that are not implied by the data or schema."
    )
    user_prompt = f"Build a HITL review from this alignment failure context:\n{json.dumps(context, default=str)}"

    try:
        client = _client()
        if LLM_PROVIDER == "anthropic":
            result: HitlReview = await client.messages.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=HitlReview,
                max_tokens=4096,
            )
        else:
            response = await client.beta.chat.completions.parse(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=HitlReview,
                temperature=0.0,
                max_tokens=4096,
            )
            result = response.choices[0].message.parsed if response.choices else None
            if result is None:
                return fallback.model_dump()

        if not result.proposed_extracted_data:
            result.proposed_extracted_data = fallback.proposed_extracted_data
        if not result.issues:
            result.issues = fallback.issues
        return result.model_dump()
    except Exception as e:
        logger.warning("HITL review LLM generation failed, using heuristic fallback", error=str(e))
        return fallback.model_dump()
