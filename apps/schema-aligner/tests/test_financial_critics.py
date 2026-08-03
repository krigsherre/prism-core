"""Unit tests for financial critics and numeric parsing."""
import pytest
from core.financial_numerics import (
    parse_financial_number,
    parse_scale_multiplier,
    nearly_equal,
    value_grounded_in_source,
)
from core.verification import CriticAgent, Severity


@pytest.fixture
def critic():
    return CriticAgent()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234.56", 1234.56),
        ("(1,000.00)", -1000.0),
        ("$2.5M", 2_500_000.0),
        ("—", None),
        ("n/a", None),
        ("1.234,56", 1234.56),
        ("500-", -500.0),
    ],
)
def test_parse_financial_number(raw, expected):
    got = parse_financial_number(raw)
    if expected is None:
        assert got is None
    else:
        assert nearly_equal(got, expected)


def test_parse_scale_multiplier():
    assert parse_scale_multiplier("in millions") == 1_000_000.0
    assert parse_scale_multiplier("USD thousands") == 1_000.0
    assert parse_scale_multiplier(None) == 1.0


def test_balance_sheet_identity_pass(critic):
    ok, err = critic.verify(
        "standardized_balance_sheet",
        {
            "total_assets": 700,
            "total_liabilities": 300,
            "total_shareholders_equity": 400,
        },
    )
    assert ok, err


def test_balance_sheet_identity_fail(critic):
    ok, err = critic.verify(
        "standardized_balance_sheet",
        {
            "total_assets": 700,
            "total_liabilities": 300,
            "total_shareholders_equity": 350,
        },
    )
    assert not ok
    assert "total_assets" in err
    detailed = critic.verify_detailed(
        "standardized_balance_sheet",
        {
            "total_assets": 700,
            "total_liabilities": 300,
            "total_shareholders_equity": 350,
        },
    )
    hard = [r for r in detailed if not r.ok and r.severity == Severity.HARD]
    assert hard
    assert any("assets_eq_l_plus_e" in r.rule_id or "identity" in r.rule_id for r in hard)


def test_balance_sheet_completeness_gate(critic):
    ok, err = critic.verify(
        "standardized_balance_sheet",
        {"total_assets": 700, "total_liabilities": 300},
    )
    assert not ok
    assert "incomplete" in err.lower() or "completeness" in err.lower()
    detailed = critic.verify_detailed(
        "standardized_balance_sheet",
        {"total_assets": 700, "total_liabilities": 300},
    )
    assert any(
        "completeness" in r.rule_id and "identity" in r.rule_id
        for r in detailed
        if not r.ok
    )


def test_income_statement_chain(critic):
    ok, err = critic.verify(
        "standardized_income_statement",
        {
            "revenue_from_operations": 1000,
            "other_income": 20,
            "total_revenue": 1020,
            "cost_of_goods_sold": 600,
            "gross_profit": 420,
            "sg_and_a_expenses": 120,
            "r_and_d_expenses": 80,
            "operating_expenses": 200,
            "ebitda": 250,
            "depreciation_and_amortization": 30,
            "ebit": 220,
            "interest_expense": 20,
            "profit_before_tax": 200,
            "tax_expense": 50,
            "net_income": 150,
        },
    )
    assert ok, err


def test_cash_flow_identity(critic):
    ok, err = critic.verify(
        "standardized_cash_flow",
        {
            "net_cash_from_operating_activities": 180,
            "net_cash_from_investing_activities": -45,
            "net_cash_from_financing_activities": -30,
            "net_change_in_cash": 105,
        },
    )
    assert ok, err


def test_cash_flow_completeness(critic):
    ok, err = critic.verify(
        "standardized_cash_flow",
        {"net_change_in_cash": 105, "net_cash_from_operating_activities": 180},
    )
    assert not ok
    assert "incomplete" in err.lower() or "completeness" in err.lower()


def test_bank_header_identity(critic):
    ok, err = critic.verify(
        "bank_statement_headers",
        {
            "opening_balance": 1000,
            "total_deposits": 500,
            "total_withdrawals": 240,
            "total_fees": 10,
            "total_interest": 0,
            "closing_balance": 1250,
        },
    )
    assert ok, err


def test_bank_running_balance(critic):
    ok, err = critic.verify_document(
        "bank_statement_transactions",
        [
            {"deposit_amount": 100, "withdrawal_amount": None, "balance": 1100},
            {"deposit_amount": None, "withdrawal_amount": 50, "balance": 1050},
        ],
    )
    assert ok, err


def test_bank_running_balance_break(critic):
    ok, err = critic.verify_document(
        "bank_statement_transactions",
        [
            {"deposit_amount": 100, "balance": 1100},
            {"withdrawal_amount": 50, "balance": 1200},
        ],
    )
    assert not ok


def test_invoice_header(critic):
    ok, err = critic.verify(
        "vendor_invoice_headers",
        {
            "subtotal_amount": 100,
            "tax_amount": 8,
            "discount_amount": 5,
            "shipping_amount": 2,
            "total_amount": 105,
            "amount_paid": 0,
            "amount_due": 105,
        },
    )
    assert ok, err


def test_invoice_total_without_subtotal_fails(critic):
    ok, err = critic.verify(
        "vendor_invoice_headers",
        {"total_amount": 105},
    )
    assert not ok


def test_scale_aware_identity(critic):
    ok, err = critic.verify(
        "standardized_balance_sheet",
        {
            "total_assets": 700.0,
            "total_liabilities": 300.0,
            "total_shareholders_equity": 400.001,
            "context_scale": "in millions",
            "_context_scale_multiplier": 1_000_000.0,
        },
    )
    assert ok, err


def test_grounding_soft_fail(critic):
    results = critic.verify_detailed(
        "standardized_balance_sheet",
        {
            "total_assets": 700,
            "total_liabilities": 300,
            "total_shareholders_equity": 400,
        },
        source_text="Total Assets 999 Total Liabilities 300 Equity 400",
    )
    soft = [r for r in results if not r.ok and r.severity == Severity.SOFT]
    assert soft
    assert any("grounding" in r.rule_id for r in soft)
    ok, _ = critic.verify(
        "standardized_balance_sheet",
        {
            "total_assets": 700,
            "total_liabilities": 300,
            "total_shareholders_equity": 400,
        },
    )
    assert ok


def test_value_grounded_in_source():
    assert value_grounded_in_source(700, "Assets were 700 million")
    assert not value_grounded_in_source(700, "Assets were 999 million")


def test_financial_schema_fail_closed_unknown(critic):
    from core.verification import FINANCIAL_SCHEMAS

    for schema in FINANCIAL_SCHEMAS:
        assert schema in critic._row_verifiers or schema in critic._doc_verifiers


def test_synonym_remap_and_cast():
    from core.alignment import WaterfallAlignmentStrategy
    from types import SimpleNamespace

    strategy = WaterfallAlignmentStrategy()
    row = SimpleNamespace(
        model_dump=lambda: {
            "total_assets": None,
            "total_liabilities": "300",
            "total_shareholders_equity": "400",
            "context_scale": "in millions",
            "additional_metadata": {"Total Assets": "700"},
        }
    )
    schema = {
        "total_assets": "float",
        "total_liabilities": "float",
        "total_shareholders_equity": "float",
        "context_scale": "str",
    }
    strict, unmapped, status, table, drifted = strategy._cast_and_verify_rows(
        [row], schema, "standardized_balance_sheet", "tenant-1"
    )
    assert strict[0]["total_assets"] == 700.0
    assert strict[0]["total_liabilities"] == 300.0
    assert status == "MAPPED"
    assert "Total Assets" not in (unmapped[0] or {})
    assert unmapped[0].get("critic_version") == "v3"
    assert "confidence_score" in unmapped[0]
    assert "promotion_band" in unmapped[0]


def test_annotate_meta_hard_failure(critic):
    results = critic.verify_detailed(
        "standardized_balance_sheet",
        {"total_assets": 1, "total_liabilities": 2, "total_shareholders_equity": 3},
    )
    meta = critic.annotate_meta({}, results)
    assert meta["row_status"] == "FAILED_VERIFICATION"
    assert meta["hard_failures"]
    assert meta["critic_results"]
