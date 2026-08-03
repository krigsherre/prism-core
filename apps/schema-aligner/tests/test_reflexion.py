"""Tests for Reflexion classification and repair ladder."""
import pytest
from unittest.mock import  patch

from core.reflexion import (
    FailureClass,
    build_repair_instructions,
    classify_failure,
    tier_for_attempt,
)
from core.alignment import WaterfallAlignmentStrategy


def test_classify_retryable_logic_error():
    assert classify_failure("Logic Error: total_assets ≈ ...", status="FAILED_VERIFICATION") == FailureClass.RETRYABLE


def test_classify_permanent_unknown_table():
    assert classify_failure("could not classify", status="NEEDS_REVIEW", target_table="") == FailureClass.PERMANENT


def test_classify_permanent_hint():
    assert classify_failure("OCR returned empty", status="FAILED") == FailureClass.PERMANENT


def test_tier_for_attempt():
    assert tier_for_attempt(0) == "initial"
    assert tier_for_attempt(1) == "repair"
    assert tier_for_attempt(2) == "focused_repair"
    assert tier_for_attempt(3) == "escalated_repair"


def test_build_repair_instructions_includes_critic():
    text = build_repair_instructions(
        critic_error="Logic Error: Assets ≠ L+E",
        previous_rows=[{"total_assets": 100}],
        attempt_index=1,
        target_table="standardized_balance_sheet",
    )
    assert "Logic Error" in text
    assert "REFLEXION REPAIR MODE" in text
    assert "standardized_balance_sheet" in text


def test_build_repair_instructions_includes_few_shots():
    text = build_repair_instructions(
        critic_error="Logic Error: Assets ≠ L+E",
        previous_rows=[{"total_assets": 100}],
        attempt_index=1,
        target_table="standardized_balance_sheet",
        few_shot_examples=[
            {
                "critic_error": "Assets ≠ L+E",
                "field_patches": [
                    {"column": "total_shareholders_equity", "before": 350, "after": 400}
                ],
            }
        ],
    )
    assert "FEW-SHOT FROM PRIOR HITL" in text
    assert "total_shareholders_equity" in text


@pytest.mark.asyncio
async def test_align_with_reflexion_stops_on_success():
    strategy = WaterfallAlignmentStrategy()
    calls = {"n": 0}

    async def fake_align(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                [{"total_assets": 700, "total_liabilities": 300, "total_shareholders_equity": 350}],
                [{"critic_error": "Logic Error: total_assets", "row_status": "FAILED_VERIFICATION"}],
                "FAILED_VERIFICATION",
                "standardized_balance_sheet",
                [],
            )
        return (
            [{"total_assets": 700, "total_liabilities": 300, "total_shareholders_equity": 400}],
            [{"row_status": "MAPPED"}],
            "MAPPED",
            "standardized_balance_sheet",
            [],
        )

    with patch.object(strategy, "align", side_effect=fake_align):
        with patch("core.alignment.settings") as mock_settings:
            mock_settings.max_reflexion_attempts = 3
            strict, unmapped, status, table, drifted, meta = await strategy.align_with_reflexion(
                "t1",
                "standardized_balance_sheet",
                {"x": 1},
                markdown_content="Balance Sheet",
            )

    assert status == "MAPPED"
    assert calls["n"] == 2
    assert meta["repaired"] is True
    assert meta["attempts"] == 2
    assert meta["exhausted"] is False


@pytest.mark.asyncio
async def test_align_with_reflexion_permanent_skips_budget():
    strategy = WaterfallAlignmentStrategy()
    calls = {"n": 0}

    async def fake_align(**kwargs):
        calls["n"] += 1
        return ([], [{"critic_error": "OCR returned empty"}], "FAILED", "", [])

    with patch.object(strategy, "align", side_effect=fake_align):
        with patch("core.alignment.settings") as mock_settings:
            mock_settings.max_reflexion_attempts = 3
            strict, unmapped, status, table, drifted, meta = await strategy.align_with_reflexion(
                "t1", "", {}, markdown_content=""
            )

    assert status == "FAILED"
    assert calls["n"] == 1 
    assert meta["exhausted"] is True
    assert meta["failure_class"] == FailureClass.PERMANENT.value


@pytest.mark.asyncio
async def test_align_with_reflexion_exhausts_retryable():
    strategy = WaterfallAlignmentStrategy()

    async def always_fail(**kwargs):
        return (
            [{"total_assets": 1}],
            [{"critic_error": "Logic Error: total_assets mismatch", "row_status": "FAILED_VERIFICATION"}],
            "FAILED_VERIFICATION",
            "standardized_balance_sheet",
            [],
        )

    with patch.object(strategy, "align", side_effect=always_fail):
        with patch("core.alignment.settings") as mock_settings:
            mock_settings.max_reflexion_attempts = 3
            strict, unmapped, status, table, drifted, meta = await strategy.align_with_reflexion(
                "t1",
                "standardized_balance_sheet",
                {"x": 1},
                "Balance Sheet",
            )

    assert status == "FAILED_VERIFICATION"
    assert meta["attempts"] == 3
    assert meta["exhausted"] is True
    assert "reflexion_meta" in unmapped[0]
