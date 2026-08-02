"""Unit tests for HITL correction flywheel helpers."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.corrections import (
    compute_field_patches,
    correction_to_golden,
    detect_synonym_mappings,
    dictionary_cdc_event,
    format_few_shot_block,
    persist_correction,
)


def test_compute_field_patches_diff():
    before = {"total_assets": 100, "cash": 10}
    after = {"total_assets": 700, "cash": 10}
    patches = compute_field_patches(before, after)
    assert len(patches) == 1
    assert patches[0]["column"] == "total_assets"
    assert patches[0]["before"] == 100
    assert patches[0]["after"] == 700


def test_detect_synonym_from_additional_metadata():
    before = {
        "additional_metadata": {"Total Assets": 700},
        "total_assets": None,
    }
    after = {"total_assets": 700, "additional_metadata": {}}
    mappings = detect_synonym_mappings(before, after)
    assert {"raw_label": "Total Assets", "mapped_column": "total_assets"} in mappings


def test_dictionary_cdc_event_shape():
    event = dictionary_cdc_event(
        tenant_id="t1",
        target_table="standardized_balance_sheet",
        raw_label="Cash & Equiv.",
        mapped_column="cash_and_equivalents",
    )
    after = event["payload"]["after"]
    assert event["payload"]["op"] == "c"
    assert after["tenant_id"] == "t1"
    assert after["raw_label"] == "Cash & Equiv."
    assert after["mapped_column"] == "cash_and_equivalents"


def test_correction_to_golden_shape():
    golden = correction_to_golden(
        {
            "id": "corr-1",
            "document_id": "doc-9",
            "target_table": "standardized_balance_sheet",
            "after_data": {"total_assets": 700, "total_liabilities": 300},
            "field_patches": [
                {"column": "total_assets", "before": 100, "after": 700},
            ],
            "critic_error": "Logic Error",
        }
    )
    assert golden["document_id"] == "hitl_doc-9"
    assert golden["target_table"] == "standardized_balance_sheet"
    assert golden["cells"][0]["column"] == "total_assets"
    assert golden["cells"][0]["value"] == 700


def test_format_few_shot_block():
    text = format_few_shot_block(
        [
            {
                "critic_error": "Assets ≠ L+E",
                "field_patches": [
                    {"column": "total_shareholders_equity", "before": 350, "after": 400}
                ],
            }
        ]
    )
    assert "FEW-SHOT FROM PRIOR HITL" in text
    assert "total_shareholders_equity" in text
    assert "350" in text


@pytest.mark.asyncio
async def test_persist_correction_inserts():
    conn = AsyncMock()
    conn.execute = AsyncMock()

    record = await persist_correction(
        conn,
        tenant_id="t1",
        document_id="doc-1",
        hitl_request_id="hitl-1",
        original_payload={
            "target_table": "standardized_balance_sheet",
            "extracted_data": {
                "total_assets": 100,
                "additional_metadata": {"Total Assets": 700},
            },
            "unmapped_jsonb": [{"critic_error": "Logic Error: total_assets"}],
        },
        after_data={"total_assets": 700, "total_liabilities": 300, "total_shareholders_equity": 400},
    )

    assert record["id"]
    assert record["critic_error"].startswith("Logic Error")
    assert any(p["column"] == "total_assets" for p in record["field_patches"])
    conn.execute.assert_awaited()
    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO extraction_corrections" in sql
