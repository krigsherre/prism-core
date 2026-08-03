import pytest
from core.financial_numerics import parse_financial_number, parse_scale_multiplier
from core.doc_router import detect_jurisdiction
from core.alignment import WaterfallAlignmentStrategy


def test_indian_crores_and_lakhs_scaling():
    """Verify Crores (10^7) and Lakhs (10^5) scale multipliers."""
    # ₹ in Crores footnote
    crores_scale = parse_scale_multiplier("₹ in Crores")
    assert crores_scale == 10_000_000.0

    # Rs. in Lakhs footnote
    lakhs_scale = parse_scale_multiplier("Rs. in Lakhs")
    assert lakhs_scale == 100_000.0

    # Shorthand Cr footnote
    cr_scale = parse_scale_multiplier("(in Cr.)")
    assert cr_scale == 10_000_000.0


def test_indian_number_parsing():
    """Verify numeric parsing for Indian 2-digit comma grouping."""
    # 1 Crore formatted as 1,00,00,000
    val_cr = parse_financial_number("1,00,00,000")
    assert val_cr == 10_000_000.0

    # 10 Lakhs formatted as 10,00,000
    val_lakh = parse_financial_number("10,00,000")
    assert val_lakh == 1_000_000.0

    # Negative accounting with Rs symbol
    neg_val = parse_financial_number("(Rs. 5,00,000)")
    assert neg_val == -500_000.0


def test_indian_ind_as_aliases():
    """Verify Ind AS / Schedule III terminology aliases map correctly."""
    strategy = WaterfallAlignmentStrategy()

    # PAT / Profit for the year -> net_income
    assert strategy.financial_aliases.get("profit for the year") == "net_income"
    assert strategy.financial_aliases.get("profit after tax") == "net_income"
    assert strategy.financial_aliases.get("pat") == "net_income"

    # Finance costs -> interest_expense
    assert strategy.financial_aliases.get("finance costs") == "interest_expense"

    # PBT -> profit_before_tax
    assert strategy.financial_aliases.get("pbt") == "profit_before_tax"

    # Employee benefits expense -> sg_and_a_expenses
    assert strategy.financial_aliases.get("employee benefits expense") == "sg_and_a_expenses"

    # CWIP -> property_plant_equipment
    assert strategy.financial_aliases.get("capital work in progress") == "property_plant_equipment"


def test_detect_jurisdiction():
    """Verify document jurisdiction classifier distinguishes IND vs US."""
    indian_text = """
    RELIANCE INDUSTRIES LIMITED
    Standalone Balance Sheet as at March 31, 2024
    (Prepared in accordance with Ind AS under Companies Act, 2013)
    Amounts in ₹ Crores. CIN: L17110MH1973PLC019786
    """
    assert detect_jurisdiction(indian_text) == "IND"

    us_text = """
    UNITED STATES SECURITIES AND EXCHANGE COMMISSION
    Washington, D.C. 20549
    FORM 10-K
    APPLE INC. - Commission File Number: 001-36743
    Prepared in accordance with US-GAAP. $ in millions.
    """
    assert detect_jurisdiction(us_text) == "US"
