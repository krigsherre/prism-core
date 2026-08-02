"""Cross-schema critics (header↔lines, bank close, statement cash)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.critic_types import CriticResult, Severity
from core.financial_numerics import fget, nearly_equal, scale_from_row

Row = Dict[str, Any]
DocBundle = Dict[str, List[Row]]


def verify_invoice_header_vs_lines(header_rows: List[Row], line_rows: List[Row]) -> List[CriticResult]:
    if not header_rows or not line_rows:
        return []
    header = header_rows[0]
    total = fget(header, "total_amount")
    subtotal = fget(header, "subtotal_amount", "subtotal")
    scale = scale_from_row(header)
    line_sum = 0.0
    any_line = False
    for row in line_rows:
        val = fget(row, "total_amount", "total_price", "amount")
        if val is not None:
            line_sum += val
            any_line = True
    if not any_line:
        return []

    target = subtotal if subtotal is not None else total
    label = "subtotal_amount" if subtotal is not None else "total_amount"
    if target is None or nearly_equal(line_sum, target, scale=scale):
        return []

    severity = Severity.HARD if subtotal is not None else Severity.SOFT
    return [
        CriticResult.fail(
            "cross.inv.header_vs_lines",
            f"Logic Error: Σ line items ({line_sum}) ≠ header {label} ({target})",
            fields=["total_amount", "subtotal_amount", "invoice_line_items"],
            expected=target,
            actual=line_sum,
            severity=severity,
            actionable_hint="Reconcile line totals with invoice header subtotal/total.",
        )
    ]


def verify_bank_header_vs_transactions(header_rows: List[Row], tx_rows: List[Row]) -> List[CriticResult]:
    if not header_rows or not tx_rows:
        return []
    header = header_rows[0]
    closing = fget(header, "closing_balance", "ending_balance")
    opening = fget(header, "opening_balance", "beginning_balance")
    scale = scale_from_row(header)
    out: List[CriticResult] = []

    last_bal = None
    for row in tx_rows:
        bal = fget(row, "balance")
        if bal is not None:
            last_bal = bal
    if closing is not None and last_bal is not None and not nearly_equal(closing, last_bal, scale=scale):
        out.append(
            CriticResult.fail(
                "cross.bank.closing_vs_last_tx",
                f"Logic Error: header closing ({closing}) ≠ last transaction balance ({last_bal})",
                fields=["closing_balance", "balance"],
                expected=closing,
                actual=last_bal,
                actionable_hint="Align statement closing balance with the final running balance.",
            )
        )

    first_bal = fget(tx_rows[0], "balance")
    first_dep = fget(tx_rows[0], "deposit_amount") or 0.0
    first_wd = fget(tx_rows[0], "withdrawal_amount") or 0.0
    if opening is not None and first_bal is not None:
        implied_open = first_bal - first_dep + first_wd
        if not nearly_equal(opening, implied_open, scale=scale):
            out.append(
                CriticResult.fail(
                    "cross.bank.opening_vs_first_tx",
                    f"Logic Error: header opening ({opening}) inconsistent with first tx "
                    f"(balance {first_bal} − deposit {first_dep} + withdrawal {first_wd} ⇒ {implied_open})",
                    fields=["opening_balance", "balance"],
                    expected=opening,
                    actual=implied_open,
                    severity=Severity.SOFT,
                    actionable_hint="Check opening balance against the first transaction.",
                )
            )
    return out


def verify_bs_cf_cash(bs_rows: List[Row], cf_rows: List[Row]) -> List[CriticResult]:
    if not bs_rows or not cf_rows:
        return []
    bs, cf = bs_rows[0], cf_rows[0]
    cash = fget(bs, "cash_and_equivalents")
    change = fget(cf, "net_change_in_cash")
    prior_cash = fget(bs, "prior_cash_and_equivalents", "beginning_cash")
    if prior_cash is None:
        prior_cash = fget(cf, "beginning_cash", "cash_at_beginning")
    ending_cf = fget(cf, "cash_at_end", "ending_cash")
    out: List[CriticResult] = []
    scale = scale_from_row(bs)

    if ending_cf is not None and cash is not None and not nearly_equal(ending_cf, cash, scale=scale):
        out.append(
            CriticResult.fail(
                "cross.stmt.cf_ending_vs_bs_cash",
                f"Logic Error: CF ending cash ({ending_cf}) ≠ BS cash ({cash})",
                fields=["cash_and_equivalents", "cash_at_end"],
                expected=cash,
                actual=ending_cf,
                severity=Severity.SOFT,
                actionable_hint="Reconcile cash on the balance sheet with cash flow ending cash.",
            )
        )

    if prior_cash is not None and cash is not None and change is not None:
        expected_change = cash - prior_cash
        if not nearly_equal(change, expected_change, scale=scale):
            out.append(
                CriticResult.fail(
                    "cross.stmt.cf_change_vs_bs_delta",
                    f"Logic Error: net_change_in_cash ({change}) ≠ Δ BS cash ({expected_change})",
                    fields=["net_change_in_cash", "cash_and_equivalents"],
                    expected=expected_change,
                    actual=change,
                    severity=Severity.SOFT,
                    actionable_hint="Ensure cash flow net change matches period cash movement.",
                )
            )
    return out


def verify_is_cf_net_income(is_rows: List[Row], cf_rows: List[Row]) -> List[CriticResult]:
    if not is_rows or not cf_rows:
        return []
    ni_is = fget(is_rows[0], "net_income")
    ni_cf = fget(cf_rows[0], "net_income", "profit_for_the_period")
    if ni_is is None or ni_cf is None:
        return []
    scale = scale_from_row(is_rows[0])
    if nearly_equal(ni_is, ni_cf, scale=scale):
        return []
    return [
        CriticResult.fail(
            "cross.stmt.is_vs_cf_net_income",
            f"Logic Error: IS net_income ({ni_is}) ≠ CF net_income ({ni_cf})",
            fields=["net_income"],
            expected=ni_is,
            actual=ni_cf,
            severity=Severity.SOFT,
            actionable_hint="Net income should match across income statement and cash flow.",
        )
    ]


def verify_document_bundle(bundle: DocBundle) -> List[CriticResult]:
    out: List[CriticResult] = []
    out.extend(
        verify_invoice_header_vs_lines(
            bundle.get("vendor_invoice_headers") or [],
            bundle.get("invoice_line_items") or [],
        )
    )
    out.extend(
        verify_bank_header_vs_transactions(
            bundle.get("bank_statement_headers") or [],
            bundle.get("bank_statement_transactions") or [],
        )
    )
    out.extend(
        verify_bs_cf_cash(
            bundle.get("standardized_balance_sheet") or [],
            bundle.get("standardized_cash_flow") or [],
        )
    )
    out.extend(
        verify_is_cf_net_income(
            bundle.get("standardized_income_statement") or [],
            bundle.get("standardized_cash_flow") or [],
        )
    )
    return out


def attach_related_and_verify(
    schema_name: str,
    rows: List[Row],
    related: Optional[DocBundle] = None,
) -> List[CriticResult]:
    bundle: DocBundle = dict(related or {})
    if rows and isinstance(rows[0].get("_related"), dict):
        for k, v in rows[0]["_related"].items():
            if isinstance(v, list):
                bundle.setdefault(k, v)
            elif isinstance(v, dict):
                bundle.setdefault(k, [v])
    bundle[schema_name] = rows
    return verify_document_bundle(bundle)
