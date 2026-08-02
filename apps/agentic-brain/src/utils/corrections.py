"""HITL learning flywheel: persist corrections, emit synonyms, fetch few-shots."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

_SKIP_KEYS = {
    "additional_metadata",
    "critic_error",
    "row_status",
    "reflexion_meta",
    "_context_scale_multiplier",
    "_raw_additional_metadata",
}


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return dict(value[0])
        return {}
    return {}


def _normalize_scalar(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def compute_field_patches(before: Any, after: Any) -> List[Dict[str, Any]]:
    """Diff before/after extraction into per-field patches."""
    before_d = _as_dict(before)
    after_d = _as_dict(after)
    if isinstance(after, list) and after and isinstance(after[0], dict):
        after_d = dict(after[0])
    if isinstance(before, list) and before and isinstance(before[0], dict):
        before_d = dict(before[0])

    patches: List[Dict[str, Any]] = []
    keys = set(before_d.keys()) | set(after_d.keys())
    for key in sorted(keys):
        if key in _SKIP_KEYS or str(key).startswith("_"):
            continue
        b = before_d.get(key)
        a = after_d.get(key)
        if _normalize_scalar(b) != _normalize_scalar(a):
            patches.append({"column": key, "before": b, "after": a})
    return patches


def detect_synonym_mappings(
    before: Any,
    after: Any,
    *,
    field_name: str = "",
) -> List[Dict[str, str]]:
    """Infer header→column remaps from HITL edits (additional_metadata drift)."""
    mappings: List[Dict[str, str]] = []
    before_d = _as_dict(before)
    after_d = _as_dict(after)

    before_meta = before_d.get("additional_metadata") if isinstance(before_d.get("additional_metadata"), dict) else {}

    for raw_label, raw_val in (before_meta or {}).items():
        if not isinstance(raw_label, str):
            continue
        for col, after_val in after_d.items():
            if col in _SKIP_KEYS:
                continue
            if _normalize_scalar(raw_val) and _normalize_scalar(raw_val) == _normalize_scalar(after_val):
                if col != raw_label:
                    mappings.append({"raw_label": raw_label, "mapped_column": col})

    seen = set()
    unique: List[Dict[str, str]] = []
    for m in mappings:
        key = (m["raw_label"].strip().lower(), m["mapped_column"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)
    return unique


def correction_to_golden(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a stored correction into evals/golden fixture shape."""
    after = row.get("after_data") or {}
    extracted_rows: List[Dict[str, Any]] = []
    extracted_row: Dict[str, Any] = {}

    if isinstance(after, list):
        extracted_rows = [dict(x) for x in after if isinstance(x, dict)]
        extracted_row = dict(extracted_rows[0]) if extracted_rows else {}
    else:
        extracted_row = _as_dict(after)
        if extracted_row:
            extracted_rows = [extracted_row]

    patches = row.get("field_patches") or []
    cells = []
    for p in patches:
        if not isinstance(p, dict):
            continue
        col = p.get("column")
        if not col:
            continue
        cells.append(
            {
                "row_index": int(p.get("row_index") or 0),
                "column": col,
                "value": p.get("after"),
                "tolerance": 0.01,
            }
        )
    if not cells and extracted_row:
        for k, v in extracted_row.items():
            if k in _SKIP_KEYS or str(k).startswith("context_") or str(k).startswith("_"):
                continue
            cells.append({"row_index": 0, "column": k, "value": v, "tolerance": 0.01})

    doc_id = row.get("document_id") or "correction"
    target = row.get("target_table") or "UNKNOWN_TABLE"
    payload: Dict[str, Any] = {
        "document_id": f"hitl_{doc_id}",
        "target_table": target,
        "predicted_table": target,
        "cells": cells,
        "relations": [],
        "_source": "hitl_correction",
        "_correction_id": row.get("id"),
        "_critic_error": row.get("critic_error"),
    }
    if len(extracted_rows) > 1:
        payload["extracted_rows"] = extracted_rows
    else:
        payload["extracted_row"] = extracted_row
    return payload


def dictionary_cdc_event(
    *,
    tenant_id: str,
    target_table: str,
    raw_label: str,
    mapped_column: str,
) -> Dict[str, Any]:
    """Debezium-shaped event consumed by DictionaryCDCConsumer."""
    return {
        "payload": {
            "op": "c",
            "after": {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "target_table": target_table,
                "raw_label": raw_label,
                "mapped_column": mapped_column,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    }


def format_few_shot_block(examples: List[Dict[str, Any]]) -> str:
    if not examples:
        return ""
    lines = ["- FEW-SHOT FROM PRIOR HITL CORRECTIONS (same schema):"]
    for i, ex in enumerate(examples, start=1):
        patches = ex.get("field_patches") or []
        critic = ex.get("critic_error") or ""
        after = ex.get("after_data")
        lines.append(f"  Example {i}: critic was '{critic}'")
        if patches:
            for p in patches[:8]:
                lines.append(
                    f"    {p.get('column')}: {p.get('before')!r} → {p.get('after')!r}"
                )
        elif after:
            lines.append(f"    corrected row: {json.dumps(_as_dict(after), default=str)[:400]}")
    lines.append("- Apply the same correction pattern when the critic error is similar.")
    return "\n".join(lines) + "\n"


async def persist_correction(
    conn: Any,
    *,
    tenant_id: str,
    document_id: str,
    hitl_request_id: str = "",
    original_payload: Dict[str, Any],
    after_data: Any,
    field_name: str = "",
) -> Dict[str, Any]:
    """Insert extraction_corrections row; return the stored record dict."""
    before = (
        original_payload.get("strict_columns")
        or original_payload.get("extracted_data")
        or {}
    )
    if not before:
        before = original_payload.get("extracted_data") or {}

    patches = compute_field_patches(before, after_data)
    synonyms = detect_synonym_mappings(before, after_data, field_name=field_name)

    unmapped = original_payload.get("unmapped_jsonb")
    if isinstance(unmapped, list) and unmapped and isinstance(unmapped[0], dict):
        drift = {k: v for k, v in unmapped[0].items() if k not in _SKIP_KEYS}
        fake_before = {"additional_metadata": drift}
        synonyms.extend(detect_synonym_mappings(fake_before, after_data))
        seen = set()
        uniq = []
        for m in synonyms:
            key = (m["raw_label"].strip().lower(), m["mapped_column"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(m)
        synonyms = uniq

    critic_error = ""
    if isinstance(unmapped, list) and unmapped and isinstance(unmapped[0], dict):
        critic_error = str(unmapped[0].get("critic_error") or "")
    critic_error = critic_error or str(original_payload.get("error") or "")

    correction_id = str(uuid.uuid4())
    record = {
        "id": correction_id,
        "tenant_id": tenant_id,
        "document_id": document_id,
        "node_id": original_payload.get("node_id"),
        "target_table": original_payload.get("target_table"),
        "source_page": original_payload.get("source_page"),
        "source_bbox": original_payload.get("source_bbox"),
        "critic_error": critic_error,
        "before_data": before,
        "after_data": after_data,
        "field_patches": patches,
        "synonym_mappings": synonyms,
        "reflexion_meta": original_payload.get("reflexion_meta"),
        "hitl_request_id": hitl_request_id or None,
        "promoted_to_eval": False,
    }

    await conn.execute(
        """
        INSERT INTO extraction_corrections (
            id, tenant_id, document_id, node_id, target_table, source_page, source_bbox,
            critic_error, before_data, after_data, field_patches, synonym_mappings,
            reflexion_meta, hitl_request_id, promoted_to_eval
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11::jsonb,$12::jsonb,$13::jsonb,$14,$15
        )
        """,
        record["id"],
        record["tenant_id"],
        record["document_id"],
        record["node_id"],
        record["target_table"],
        record["source_page"],
        record["source_bbox"],
        record["critic_error"],
        json.dumps(record["before_data"], default=str),
        json.dumps(record["after_data"], default=str),
        json.dumps(record["field_patches"], default=str),
        json.dumps(record["synonym_mappings"], default=str),
        json.dumps(record["reflexion_meta"], default=str) if record["reflexion_meta"] is not None else None,
        record["hitl_request_id"],
        False,
    )
    logger.info(
        "Persisted extraction correction",
        correction_id=correction_id,
        document_id=document_id,
        patches=len(patches),
        synonyms=len(synonyms),
    )
    return record


async def fetch_few_shot_corrections(
    conn: Any,
    *,
    tenant_id: str,
    target_table: str,
    limit: int = 3,
    critic_error: str = "",
    rule_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Fetch recent HITL corrections for few-shot repair.
    Prefer examples whose critic_error matches rule_id / error substring.
    """
    if not target_table:
        return []
    rows = await conn.fetch(
        """
        SELECT id, critic_error, field_patches, after_data, before_data, target_table
        FROM extraction_corrections
        WHERE tenant_id = $1 AND target_table = $2
        ORDER BY created_at DESC
        LIMIT $3
        """,
        tenant_id,
        target_table,
        max(limit * 4, 12),
    )
    out: List[Dict[str, Any]] = []
    needle = (rule_id or "").strip()
    if not needle and critic_error:
        import re

        m = re.search(r"\[([a-z0-9_.]+)\]", critic_error, re.IGNORECASE)
        if m:
            needle = m.group(1)
        else:
            needle = critic_error[:80]

    ranked: List[tuple] = []
    for r in rows:
        err = str(r["critic_error"] or "")
        score = 0
        if needle and needle.lower() in err.lower():
            score += 10
        ranked.append((score, r))
    ranked.sort(key=lambda x: (-x[0],))

    for score, r in ranked[:limit]:
        out.append(
            {
                "id": r["id"],
                "critic_error": r["critic_error"],
                "field_patches": r["field_patches"],
                "after_data": r["after_data"],
                "before_data": r["before_data"],
                "target_table": r["target_table"],
                "match_score": score,
            }
        )
    return out


async def list_unpromoted_corrections(conn: Any, *, limit: int = 200) -> List[Dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, document_id, target_table, critic_error,
               before_data, after_data, field_patches, synonym_mappings, promoted_to_eval
        FROM extraction_corrections
        WHERE promoted_to_eval = false
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def mark_promoted(conn: Any, correction_ids: List[str]) -> None:
    if not correction_ids:
        return
    await conn.execute(
        "UPDATE extraction_corrections SET promoted_to_eval = true WHERE id = ANY($1::text[])",
        correction_ids,
    )
