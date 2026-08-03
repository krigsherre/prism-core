import pytest
from core.financial_numerics import parse_financial_number, scale_from_row, _UNSCALED_FIELDS
from core.doc_router import route_document

def test_unscaled_fields_eps_protection():
    """Verify EPS and Share Counts bypass context scale multipliers (e.g. in millions)."""
    # Context scale text specifies 'in millions'
    row_context = {"context_scale": "in millions", "_context_scale_multiplier": 1_000_000.0}

    # Revenue should scale by 1,000,000
    rev_scale = scale_from_row(row_context, field_name="total_revenue")
    assert rev_scale == 1_000_000.0

    # Basic EPS must NOT scale by 1,000,000 (must stay 1.0)
    eps_scale = scale_from_row(row_context, field_name="eps_basic")
    assert eps_scale == 1.0

    # Diluted EPS must NOT scale
    diluted_eps_scale = scale_from_row(row_context, field_name="eps_diluted")
    assert diluted_eps_scale == 1.0

    # Basic weighted average shares must NOT scale
    shares_scale = scale_from_row(row_context, field_name="weighted_average_shares_basic")
    assert shares_scale == 1.0


def test_parse_financial_number_field_awareness():
    """Verify parse_financial_number leaves EPS decimal numbers uncorrupted."""
    # EPS value of 6.16 should be parsed as 6.16 even if field name is provided
    eps_val = parse_financial_number("6.16", field_name="eps_basic")
    assert eps_val == 6.16

    # Diluted EPS of $ 12.45
    diluted_val = parse_financial_number("$ 12.45", field_name="eps_diluted")
    assert diluted_val == 12.45

    # Parentheses accounting negative for EPS
    neg_eps = parse_financial_number("(0.85)", field_name="eps_basic")
    assert neg_eps == -0.85


def test_sec_10k_title_routing():
    """Verify SEC 10-K consolidated titles route correctly."""
    routed, score, _ = route_document("CONSOLIDATED STATEMENTS OF OPERATIONS\nTotal Revenue: 100,000", min_score=0.5)
    assert routed == "standardized_income_statement"

    routed_bs, score_bs, _ = route_document("CONSOLIDATED BALANCE SHEETS\nTotal Assets: 500,000", min_score=0.5)
    assert routed_bs == "standardized_balance_sheet"

    routed_cf, score_cf, _ = route_document("CONSOLIDATED STATEMENTS OF CASH FLOWS\nNet Cash Provided by Operating Activities", min_score=0.5)
    assert routed_cf == "standardized_cash_flow"

    routed_note, score_note, _ = route_document("Note 12 - Segment Reporting\nDisaggregated revenue by geography", min_score=0.5)
    assert routed_note == "sec_10k_footnote_schedule"


def test_ixbrl_fast_path_parser():
    """Verify iXBRL parser extracts US-GAAP tags directly from HTML."""
    from core.ixbrl_parser import is_ixbrl_content, parse_ixbrl_facts

    sample_html = '<ix:nonFraction name="us-gaap:Revenues">96995000000</ix:nonFraction>'
    assert is_ixbrl_content(sample_html) is True

    facts = parse_ixbrl_facts(sample_html)
    assert facts.get("Revenues") == "96995000000"


def test_unpivot_multi_period_table():
    """Verify comparative year columns (2024, 2023) are unpivoted into temporal rows."""
    from core.alignment import WaterfallAlignmentStrategy

    strategy = WaterfallAlignmentStrategy()
    pivoted_row = [{"line_item": "Revenue", "2024": "1000", "2023": "900"}]
    unpivoted = strategy._unpivot_multi_period_table(pivoted_row)

    assert len(unpivoted) == 2
    periods = {r["context_reporting_period"]: r["amount"] for r in unpivoted}
    assert periods["2024"] == "1000"
    assert periods["2023"] == "900"

