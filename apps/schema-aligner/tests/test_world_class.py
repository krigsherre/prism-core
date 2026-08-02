"""Tests for domain packs, cross-entity critics, confidence, and doc router."""
from core.confidence import compute_confidence, PromotionBand, band_to_status
from core.cross_entity import (
    verify_bank_header_vs_transactions,
    verify_bs_cf_cash,
    verify_document_bundle,
    verify_invoice_header_vs_lines,
)
from core.critic_types import CriticResult, Severity
from core.doc_router import route_document
from core.rule_engine import load_packs, eval_pack_rules
from core.verification import CriticAgent


def test_domain_packs_load():
    packs = load_packs()
    names = {p.name for p in packs}
    assert "financial_statements" in names
    assert "banking" in names
    assert "invoicing" in names


def test_pack_rules_balance_sheet():
    packs = load_packs()
    fs = next(p for p in packs if p.name == "financial_statements")
    rules = fs.rules["standardized_balance_sheet"]
    results = eval_pack_rules(
        rules,
        {"total_assets": 100, "total_liabilities": 40, "total_shareholders_equity": 50},
    )
    hard = [r for r in results if not r.ok and r.severity == Severity.HARD]
    assert hard
    assert any("identity" in r.rule_id for r in hard)


def test_critic_agent_uses_packs():
    critic = CriticAgent()
    assert critic.packs
    ok, err = critic.verify(
        "standardized_balance_sheet",
        {"total_assets": 700, "total_liabilities": 300},
    )
    assert not ok
    assert "completeness" in err.lower() or "incomplete" in err.lower()


def test_cross_invoice_header_lines():
    results = verify_invoice_header_vs_lines(
        [{"subtotal_amount": 100, "total_amount": 110}],
        [{"total_amount": 40}, {"total_amount": 50}],
    )
    assert results
    assert results[0].rule_id == "cross.inv.header_vs_lines"


def test_cross_bank_closing():
    results = verify_bank_header_vs_transactions(
        [{"opening_balance": 1000, "closing_balance": 1200}],
        [
            {"deposit_amount": 100, "balance": 1100},
            {"withdrawal_amount": 50, "balance": 1050},
        ],
    )
    assert any(r.rule_id == "cross.bank.closing_vs_last_tx" for r in results if not r.ok)


def test_cross_bs_cf_cash():
    results = verify_bs_cf_cash(
        [{"cash_and_equivalents": 200, "prior_cash_and_equivalents": 100}],
        [{"net_change_in_cash": 50, "cash_at_end": 200}],
    )
    assert any("cf_change" in r.rule_id for r in results if not r.ok)


def test_cross_bundle():
    results = verify_document_bundle(
        {
            "vendor_invoice_headers": [{"subtotal_amount": 100}],
            "invoice_line_items": [{"total_amount": 100}],
        }
    )
    assert results == [] or all(r.ok for r in results) or True  # matching OK
    # exact match → no failures
    assert not [r for r in results if not r.ok]


def test_doc_router_balance_sheet():
    schema, score, _ = route_document(
        "Consolidated Balance Sheet\nTotal Assets 700\nShareholders Equity 400",
        allowed_schemas=[
            "standardized_balance_sheet",
            "standardized_income_statement",
            "vendor_invoice_headers",
        ],
        min_score=1.5,
    )
    assert schema == "standardized_balance_sheet"
    assert score >= 1.5


def test_doc_router_ambiguous_falls_through():
    schema, _, _ = route_document("total", min_score=1.5)
    assert schema == ""


def test_confidence_reject_on_hard():
    report = compute_confidence(
        critic_results=[CriticResult.fail("x", "boom", severity=Severity.HARD)]
    )
    assert report.band == PromotionBand.REJECT
    assert band_to_status(report.band) == "FAILED_VERIFICATION"


def test_confidence_review_on_soft():
    report = compute_confidence(
        critic_results=[CriticResult.fail("x", "soft", severity=Severity.SOFT)]
    )
    assert report.band == PromotionBand.REVIEW


def test_confidence_auto_promote_clean():
    report = compute_confidence(critic_results=[])
    assert report.band == PromotionBand.AUTO_PROMOTE
    assert report.score == 1.0
