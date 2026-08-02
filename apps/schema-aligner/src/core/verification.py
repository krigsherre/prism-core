"""Fail-closed financial critics with structured CriticResult output."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from core.critic_types import CriticResult, Severity, merge_results, results_to_meta
from core.cross_entity import attach_related_and_verify
from core.financial_numerics import (
    fget,
    nearly_equal,
    parse_financial_number,
    present_count,
    require_equal,
    scale_from_row,
    value_grounded_in_source,
)
from core.rule_engine import DomainPack, eval_pack_rules, load_packs

logger = structlog.get_logger(__name__)

Row = Dict[str, Any]
VerifyFn = Callable[[Row], Tuple[bool, str]]
VerifyRowsFn = Callable[[List[Row]], Tuple[bool, str]]
VerifyDetailedFn = Callable[[Row], List[CriticResult]]
VerifyRowsDetailedFn = Callable[[List[Row]], List[CriticResult]]

CRITIC_VERSION = "v3"


FINANCIAL_SCHEMAS = frozenset(
    {
        "standardized_balance_sheet",
        "standardized_income_statement",
        "standardized_cash_flow",
        "bank_statement_headers",
        "bank_statement_transactions",
        "vendor_invoice_headers",
        "invoice_line_items",
        "purchase_order_headers",
        "purchase_order_line_items",
        "receipt_headers",
        "receipt_line_items",
        "tax_form_headers",
        "utility_bills",
    }
)

_GROUNDING_FIELDS: Dict[str, Tuple[str, ...]] = {
    "standardized_balance_sheet": (
        "total_assets",
        "total_liabilities",
        "total_shareholders_equity",
        "cash_and_equivalents",
        "net_income",
    ),
    "standardized_income_statement": (
        "total_revenue",
        "gross_profit",
        "net_income",
        "ebit",
        "profit_before_tax",
    ),
    "standardized_cash_flow": (
        "net_cash_from_operating_activities",
        "net_change_in_cash",
    ),
    "vendor_invoice_headers": ("total_amount", "subtotal_amount", "tax_amount"),
    "bank_statement_headers": ("opening_balance", "closing_balance"),
}


class CriticAgent:
    """Schema-keyed row/document critics with pack rules and grounding."""

    def __init__(self, packs: Optional[List[DomainPack]] = None) -> None:
        self.packs: List[DomainPack] = packs if packs is not None else load_packs()
        self._pack_rules: Dict[str, List] = {}
        self._pack_grounding: Dict[str, Tuple[str, ...]] = dict(_GROUNDING_FIELDS)
        for pack in self.packs:
            for schema, rules in pack.rules.items():
                self._pack_rules.setdefault(schema, []).extend(rules)
            for schema, fields in pack.grounding_fields.items():
                self._pack_grounding[schema] = tuple(fields)

        self._row_detailed: Dict[str, VerifyDetailedFn] = {
            "standardized_balance_sheet": self._verify_balance_sheet,
            "standardized_income_statement": self._verify_income_statement,
            "standardized_cash_flow": self._verify_cash_flow,
            "bank_statement_headers": self._verify_bank_statement_header,
            "vendor_invoice_headers": self._verify_invoice_header,
            "invoice_line_items": self._verify_invoice_line_item,
            "purchase_order_headers": self._verify_po_header,
            "purchase_order_line_items": self._verify_po_line_item,
            "receipt_headers": self._verify_receipt_header,
            "receipt_line_items": self._verify_receipt_line_item,
            "tax_form_headers": self._verify_tax_form,
            "utility_bills": self._verify_utility_bill,
            "invoice": self._verify_invoice_header,
            "bank": self._verify_bank_statement_header,
            "statement": self._verify_bank_statement_header,
            "receipt": self._verify_receipt_header,
            "w2": self._verify_tax_form,
            "tax": self._verify_tax_form,
            "paystub": self._verify_paystub_legacy,
            "payroll": self._verify_paystub_legacy,
            "clinical": self._verify_clinical_note,
            "lab": self._verify_lab_result,
            "result": self._verify_lab_result,
        }
        self._doc_detailed: Dict[str, VerifyRowsDetailedFn] = {
            "bank_statement_transactions": self._verify_bank_transactions,
            "invoice_line_items": self._verify_line_item_math,
            "purchase_order_line_items": self._verify_line_item_math,
            "receipt_line_items": self._verify_line_item_math,
            "standardized_balance_sheet": self._rows_individually("standardized_balance_sheet"),
            "standardized_income_statement": self._rows_individually(
                "standardized_income_statement"
            ),
            "standardized_cash_flow": self._rows_individually("standardized_cash_flow"),
        }
        self._row_verifiers: Dict[str, VerifyFn] = {
            k: self._as_legacy(fn) for k, fn in self._row_detailed.items()
        }
        self._doc_verifiers: Dict[str, VerifyRowsFn] = {
            k: self._as_legacy_rows(fn) for k, fn in self._doc_detailed.items()
        }

    @staticmethod
    def _as_legacy(fn: VerifyDetailedFn) -> VerifyFn:
        def _inner(data: Row) -> Tuple[bool, str]:
            return CriticAgent._collapse(fn(data))

        return _inner

    @staticmethod
    def _as_legacy_rows(fn: VerifyRowsDetailedFn) -> VerifyRowsFn:
        def _inner(rows: List[Row]) -> Tuple[bool, str]:
            return CriticAgent._collapse(fn(rows))

        return _inner

    @staticmethod
    def _collapse(results: List[CriticResult]) -> Tuple[bool, str]:
        merged = merge_results(results)
        if merged.ok or merged.severity == Severity.SOFT:
            if merged.ok:
                return True, ""
            return True, merged.as_error_string()
        return False, merged.as_error_string()

    def _eq(
        self,
        left: Optional[float],
        right: Optional[float],
        rule_id: str,
        label: str,
        fields: List[str],
        *,
        scale: float = 1.0,
        hint: str = "",
    ) -> Optional[CriticResult]:
        if left is None or right is None:
            return None
        ok, msg = require_equal(left, right, label, scale=scale)
        if ok:
            return None
        return CriticResult.fail(
            rule_id,
            msg,
            fields=fields,
            expected=right,
            actual=left,
            actionable_hint=hint
            or f"Re-extract {', '.join(fields)} so the identity holds exactly.",
        )

    def _completeness(
        self,
        data: Row,
        rule_id: str,
        required: List[str],
        *,
        trigger_any_of: Optional[List[str]] = None,
        hint: str = "",
    ) -> Optional[CriticResult]:
        """
        If any trigger field is present (or any of `required` if no trigger),
        all `required` fields must be present — otherwise HARD fail.
        """
        triggers = trigger_any_of or required
        if present_count(data, *triggers) == 0:
            return None
        missing = [k for k in required if fget(data, k) is None]
        if not missing:
            return None
        return CriticResult.fail(
            rule_id,
            f"Logic Error: incomplete extraction — missing {missing} (required for {rule_id})",
            fields=required,
            actionable_hint=hint
            or f"Populate missing fields {missing} from the source table; do not leave identity sides null.",
        )

    def _verify_balance_sheet(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)

        comp = self._completeness(
            data,
            "bs.completeness.identity_fields",
            ["total_assets", "total_liabilities", "total_shareholders_equity"],
            trigger_any_of=["total_assets", "total_liabilities", "total_shareholders_equity"],
            hint="Balance sheet identity needs total_assets, total_liabilities, and total_shareholders_equity.",
        )
        if comp:
            out.append(comp)
            return out  # don't run identity on incomplete rows

        assets = fget(data, "total_assets")
        liabilities = fget(data, "total_liabilities")
        equity = fget(data, "total_shareholders_equity")
        if assets is not None and liabilities is not None and equity is not None:
            fail = self._eq(
                assets,
                liabilities + equity,
                "bs.identity.assets_eq_l_plus_e",
                "total_assets ≈ total_liabilities + equity",
                ["total_assets", "total_liabilities", "total_shareholders_equity"],
                scale=scale,
            )
            if fail:
                out.append(fail)

        ca = fget(data, "total_current_assets")
        cash = fget(data, "cash_and_equivalents")
        ar = fget(data, "accounts_receivable")
        inv = fget(data, "inventory")
        if ca is not None and all(v is not None for v in (cash, ar, inv)):
            component_sum = (cash or 0) + (ar or 0) + (inv or 0)
            if component_sum - ca > max(0.5, 0.01 * abs(ca), effective_min_tol(scale)):
                out.append(
                    CriticResult.fail(
                        "bs.bounds.current_assets_components",
                        f"Logic Error: cash+AR+inventory ({component_sum}) exceeds total_current_assets ({ca})",
                        fields=[
                            "cash_and_equivalents",
                            "accounts_receivable",
                            "inventory",
                            "total_current_assets",
                        ],
                        expected=ca,
                        actual=component_sum,
                    )
                )

        cl = fget(data, "total_current_liabilities")
        ap = fget(data, "accounts_payable")
        std = fget(data, "short_term_debt")
        if cl is not None and ap is not None and std is not None:
            if (ap + std) - cl > max(0.5, 0.01 * abs(cl), effective_min_tol(scale)):
                out.append(
                    CriticResult.fail(
                        "bs.bounds.current_liabilities_components",
                        f"Logic Error: AP+ST debt ({ap + std}) exceeds total_current_liabilities ({cl})",
                        fields=["accounts_payable", "short_term_debt", "total_current_liabilities"],
                        expected=cl,
                        actual=ap + std,
                    )
                )

        if assets is not None and assets < 0:
            out.append(
                CriticResult.fail(
                    "bs.bounds.assets_non_negative",
                    f"Logic Error: total_assets cannot be negative ({assets})",
                    fields=["total_assets"],
                    actual=assets,
                )
            )
        return out

    def _verify_income_statement(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)
        rev_ops = fget(data, "revenue_from_operations")
        other = fget(data, "other_income")
        total_rev = fget(data, "total_revenue")
        cogs = fget(data, "cost_of_goods_sold")
        gross = fget(data, "gross_profit")
        opex = fget(data, "operating_expenses")
        sga = fget(data, "sg_and_a_expenses")
        rnd = fget(data, "r_and_d_expenses")
        ebitda = fget(data, "ebitda")
        da = fget(data, "depreciation_and_amortization")
        ebit = fget(data, "ebit")
        interest = fget(data, "interest_expense")
        pbt = fget(data, "profit_before_tax")
        tax = fget(data, "tax_expense")
        net = fget(data, "net_income")
        for rule_id, req, triggers in (
            (
                "is.completeness.total_revenue",
                ["total_revenue", "revenue_from_operations"],
                ["total_revenue", "revenue_from_operations"],
            ),
            (
                "is.completeness.gross_profit",
                ["gross_profit", "total_revenue", "cost_of_goods_sold"],
                ["gross_profit"],
            ),
            (
                "is.completeness.net_income",
                ["net_income", "profit_before_tax", "tax_expense"],
                ["net_income"],
            ),
        ):
            if rule_id == "is.completeness.gross_profit":
                if fget(data, "gross_profit") is not None:
                    missing = [
                        k
                        for k in ("total_revenue", "cost_of_goods_sold", "revenue_from_operations")
                        if fget(data, k) is None
                    ]
                    if fget(data, "cost_of_goods_sold") is None or (
                        fget(data, "total_revenue") is None and fget(data, "revenue_from_operations") is None
                    ):
                        out.append(
                            CriticResult.fail(
                                rule_id,
                                "Logic Error: incomplete extraction — gross_profit present without revenue and COGS",
                                fields=["gross_profit", "total_revenue", "cost_of_goods_sold"],
                                actionable_hint="Extract revenue and COGS alongside gross_profit.",
                            )
                        )
                        return out
                continue
            if rule_id == "is.completeness.total_revenue":
                if present_count(data, *triggers) == 1 and fget(data, "other_income") is not None:
                    out.append(
                        CriticResult.fail(
                            rule_id,
                            "Logic Error: incomplete extraction — other_income present but total_revenue/ops incomplete",
                            fields=req,
                        )
                    )
                continue
            comp = self._completeness(data, rule_id, req, trigger_any_of=triggers)
            if comp:
                out.append(comp)
                return out

        if total_rev is not None and rev_ops is not None:
            fail = self._eq(
                total_rev,
                rev_ops + (other or 0.0),
                "is.identity.total_revenue",
                "total_revenue ≈ ops + other_income",
                ["total_revenue", "revenue_from_operations", "other_income"],
                scale=scale,
            )
            if fail:
                out.append(fail)

        if gross is not None and cogs is not None:
            if total_rev is not None:
                if not nearly_equal(gross, total_rev - cogs, scale=scale) and not (
                    rev_ops is not None and nearly_equal(gross, rev_ops - cogs, scale=scale)
                ):
                    out.append(
                        CriticResult.fail(
                            "is.identity.gross_profit",
                            f"Logic Error: gross_profit ≈ revenue − COGS — expected {total_rev - cogs}, got {gross}",
                            fields=["gross_profit", "total_revenue", "cost_of_goods_sold"],
                            expected=total_rev - cogs,
                            actual=gross,
                        )
                    )
            elif rev_ops is not None:
                fail = self._eq(
                    gross,
                    rev_ops - cogs,
                    "is.identity.gross_profit",
                    "gross_profit ≈ ops revenue − COGS",
                    ["gross_profit", "revenue_from_operations", "cost_of_goods_sold"],
                    scale=scale,
                )
                if fail:
                    out.append(fail)

        if opex is not None and sga is not None and rnd is not None:
            fail = self._eq(
                opex,
                sga + rnd,
                "is.identity.operating_expenses",
                "operating_expenses ≈ SG&A + R&D",
                ["operating_expenses", "sg_and_a_expenses", "r_and_d_expenses"],
                scale=scale,
            )
            if fail:
                out.append(fail)

        if ebit is not None and ebitda is not None and da is not None:
            fail = self._eq(
                ebit,
                ebitda - da,
                "is.identity.ebit",
                "EBIT ≈ EBITDA − D&A",
                ["ebit", "ebitda", "depreciation_and_amortization"],
                scale=scale,
            )
            if fail:
                out.append(fail)

        if pbt is not None and ebit is not None and interest is not None:
            fail = self._eq(
                pbt,
                ebit - interest,
                "is.identity.pbt",
                "PBT ≈ EBIT − interest",
                ["profit_before_tax", "ebit", "interest_expense"],
                scale=scale,
            )
            if fail:
                out.append(fail)

        if net is not None and pbt is not None and tax is not None:
            fail = self._eq(
                net,
                pbt - tax,
                "is.identity.net_income",
                "net_income ≈ PBT − tax",
                ["net_income", "profit_before_tax", "tax_expense"],
                scale=scale,
            )
            if fail:
                out.append(fail)

        return out

    def _verify_cash_flow(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)

        comp = self._completeness(
            data,
            "cf.completeness.net_change",
            [
                "net_change_in_cash",
                "net_cash_from_operating_activities",
                "net_cash_from_investing_activities",
                "net_cash_from_financing_activities",
            ],
            trigger_any_of=["net_change_in_cash"],
        )
        if comp:
            out.append(comp)
            return out

        op = fget(data, "net_cash_from_operating_activities")
        inv = fget(data, "net_cash_from_investing_activities")
        fin = fget(data, "net_cash_from_financing_activities")
        change = fget(data, "net_change_in_cash")

        if change is not None and all(v is not None for v in (op, inv, fin)):
            fail = self._eq(
                change,
                (op or 0) + (inv or 0) + (fin or 0),
                "cf.identity.net_change",
                "net_change_in_cash ≈ operating + investing + financing",
                [
                    "net_change_in_cash",
                    "net_cash_from_operating_activities",
                    "net_cash_from_investing_activities",
                    "net_cash_from_financing_activities",
                ],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_bank_statement_header(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)

        opening = fget(data, "opening_balance", "beginning_balance")
        closing = fget(data, "closing_balance", "ending_balance")
        deposits = fget(data, "total_deposits")
        withdrawals = fget(data, "total_withdrawals")
        if opening is not None or closing is not None:
            missing = []
            if opening is None:
                missing.append("opening_balance")
            if closing is None:
                missing.append("closing_balance")
            if deposits is None:
                missing.append("total_deposits")
            if withdrawals is None:
                missing.append("total_withdrawals")
            if missing:
                out.append(
                    CriticResult.fail(
                        "bank.completeness.header_balances",
                        f"Logic Error: incomplete extraction — missing {missing}",
                        fields=[
                            "opening_balance",
                            "closing_balance",
                            "total_deposits",
                            "total_withdrawals",
                        ],
                        actionable_hint="Extract opening/closing balances and deposit/withdrawal totals together.",
                    )
                )
                return out

        fees = fget(data, "total_fees") or 0.0
        interest = fget(data, "total_interest") or 0.0

        if closing is not None and opening is not None and deposits is not None and withdrawals is not None:
            expected = opening + deposits - withdrawals - fees + interest
            fail = self._eq(
                closing,
                expected,
                "bank.identity.closing_balance",
                "closing ≈ opening + deposits − withdrawals − fees + interest",
                [
                    "closing_balance",
                    "opening_balance",
                    "total_deposits",
                    "total_withdrawals",
                    "total_fees",
                    "total_interest",
                ],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_bank_transactions(self, rows: List[Row]) -> List[CriticResult]:
        out: List[CriticResult] = []
        if not rows:
            return out

        prev_balance: Optional[float] = None
        for i, row in enumerate(rows):
            bal = fget(row, "balance")
            deposit = fget(row, "deposit_amount") or 0.0
            withdrawal = fget(row, "withdrawal_amount") or 0.0
            scale = scale_from_row(row)

            if deposit and withdrawal:
                out.append(
                    CriticResult.fail(
                        "bank.tx.mutex_deposit_withdrawal",
                        f"Logic Error: row {i} has both deposit ({deposit}) and withdrawal ({withdrawal})",
                        fields=["deposit_amount", "withdrawal_amount"],
                    )
                )
                return out

            if bal is not None and deposit == 0.0 and withdrawal == 0.0 and i > 0:
                out.append(
                    CriticResult.fail(
                        "bank.tx.completeness.movement",
                        f"Logic Error: row {i} has balance but neither deposit nor withdrawal",
                        fields=["deposit_amount", "withdrawal_amount", "balance"],
                        severity=Severity.SOFT,
                        actionable_hint="Fill deposit_amount or withdrawal_amount for this row.",
                    )
                )

            if prev_balance is not None and bal is not None:
                expected = prev_balance + deposit - withdrawal
                if not nearly_equal(bal, expected, scale=scale):
                    out.append(
                        CriticResult.fail(
                            "bank.tx.running_balance",
                            f"Logic Error: running balance break at row {i} — "
                            f"prev {prev_balance} +{deposit} −{withdrawal} ≠ {bal}",
                            fields=["balance", "deposit_amount", "withdrawal_amount"],
                            expected=expected,
                            actual=bal,
                            actionable_hint=f"Fix row {i} balance or the deposit/withdrawal amounts.",
                        )
                    )
                    return out
            if bal is not None:
                prev_balance = bal
        return out

    def _verify_invoice_header(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)

        total = fget(data, "total_amount")
        subtotal = fget(data, "subtotal_amount", "subtotal")
        if total is not None and subtotal is None:
            line_items = data.get("line_items") or []
            if not (isinstance(line_items, list) and line_items):
                out.append(
                    CriticResult.fail(
                        "inv.completeness.subtotal",
                        "Logic Error: incomplete extraction — total_amount without subtotal_amount or line_items",
                        fields=["total_amount", "subtotal_amount"],
                    )
                )
                return out

        tax = fget(data, "tax_amount") or 0.0
        discount = fget(data, "discount_amount") or 0.0
        shipping = fget(data, "shipping_amount") or 0.0
        due = fget(data, "amount_due")
        paid = fget(data, "amount_paid") or 0.0

        line_items = data.get("line_items") or []
        if total is not None and isinstance(line_items, list) and line_items:
            line_sum = sum(
                parse_financial_number(item.get("amount") or item.get("total_amount")) or 0.0
                for item in line_items
                if isinstance(item, dict)
            )
            fail = self._eq(
                line_sum,
                total,
                "inv.identity.line_sum",
                "Σ line_items ≈ total_amount",
                ["line_items", "total_amount"],
                scale=scale,
            )
            if fail:
                out.append(fail)

        if total is not None and subtotal is not None:
            expected = subtotal + tax - discount + shipping
            fail = self._eq(
                total,
                expected,
                "inv.identity.total",
                "total ≈ subtotal + tax − discount + shipping",
                [
                    "total_amount",
                    "subtotal_amount",
                    "tax_amount",
                    "discount_amount",
                    "shipping_amount",
                ],
                scale=scale,
            )
            if fail:
                out.append(fail)

        if due is not None and total is not None:
            fail = self._eq(
                due,
                total - paid,
                "inv.identity.amount_due",
                "amount_due ≈ total − amount_paid",
                ["amount_due", "total_amount", "amount_paid"],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_invoice_line_item(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)
        qty = fget(data, "quantity")
        unit = fget(data, "unit_price")
        discount = fget(data, "discount_amount") or 0.0
        tax = fget(data, "tax_amount") or 0.0
        total = fget(data, "total_amount", "total_price", "amount")

        if total is not None and (qty is None or unit is None):
            out.append(
                CriticResult.fail(
                    "inv.line.completeness",
                    "Logic Error: incomplete extraction — line total without quantity and unit_price",
                    fields=["total_amount", "quantity", "unit_price"],
                )
            )
            return out

        if total is not None and qty is not None and unit is not None:
            expected = qty * unit - discount + tax
            fail = self._eq(
                total,
                expected,
                "inv.line.identity",
                "line total ≈ qty×unit − discount + tax",
                ["total_amount", "quantity", "unit_price", "discount_amount", "tax_amount"],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_po_header(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)
        subtotal = fget(data, "subtotal_amount")
        tax = fget(data, "tax_amount") or 0.0
        total = fget(data, "total_value", "total_amount")
        if total is not None and subtotal is None:
            out.append(
                CriticResult.fail(
                    "po.completeness.subtotal",
                    "Logic Error: incomplete extraction — PO total without subtotal",
                    fields=["total_value", "subtotal_amount"],
                )
            )
            return out
        if total is not None and subtotal is not None:
            fail = self._eq(
                total,
                subtotal + tax,
                "po.identity.total",
                "PO total ≈ subtotal + tax",
                ["total_value", "subtotal_amount", "tax_amount"],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_po_line_item(self, data: Row) -> List[CriticResult]:
        return self._verify_invoice_line_item(data)

    def _verify_receipt_header(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)
        subtotal = fget(data, "subtotal", "subtotal_amount") or 0.0
        tax = fget(data, "tax_amount") or 0.0
        total = fget(data, "total_amount")
        if total is not None:
            fail = self._eq(
                total,
                subtotal + tax,
                "receipt.identity.total",
                "receipt total ≈ subtotal + tax",
                ["total_amount", "subtotal", "tax_amount"],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_receipt_line_item(self, data: Row) -> List[CriticResult]:
        return self._verify_invoice_line_item(data)

    def _verify_line_item_math(self, rows: List[Row]) -> List[CriticResult]:
        out: List[CriticResult] = []
        for i, row in enumerate(rows):
            for r in self._verify_invoice_line_item(row):
                if not r.ok:
                    r.message = f"row {i}: {r.message}"
                    out.append(r)
                    if r.severity == Severity.HARD:
                        return out
        return out

    def _rows_individually(self, schema_name: str) -> VerifyRowsDetailedFn:
        def _inner(rows: List[Row]) -> List[CriticResult]:
            fn = self._row_detailed.get(schema_name)
            if not fn:
                return []
            out: List[CriticResult] = []
            for i, row in enumerate(rows):
                for r in fn(row):
                    if not r.ok:
                        r.message = f"row {i}: {r.message}"
                        out.append(r)
                        if r.severity == Severity.HARD:
                            return out
            return out

        return _inner

    def _verify_tax_form(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        ss = fget(data, "social_security_wages")
        med = fget(data, "medicare_wages")
        if ss is not None and med is not None and ss > med + 0.02:
            out.append(
                CriticResult.fail(
                    "tax.bounds.ss_vs_medicare",
                    f"Logic Error: SS wages ({ss}) cannot exceed Medicare wages ({med})",
                    fields=["social_security_wages", "medicare_wages"],
                )
            )

        state_wages = fget(data, "state_wages")
        state_tax = fget(data, "state_income_tax")
        if state_wages is not None and state_tax is not None and state_tax > state_wages + 0.02:
            out.append(
                CriticResult.fail(
                    "tax.bounds.state_tax",
                    f"Logic Error: state tax ({state_tax}) > state wages ({state_wages})",
                    fields=["state_income_tax", "state_wages"],
                )
            )

        total_income = fget(data, "total_income")
        agi = fget(data, "adjusted_gross_income")
        taxable = fget(data, "taxable_income")
        if agi is not None and total_income is not None and agi > total_income + 0.02:
            out.append(
                CriticResult.fail(
                    "tax.bounds.agi",
                    f"Logic Error: AGI ({agi}) cannot exceed total_income ({total_income})",
                    fields=["adjusted_gross_income", "total_income"],
                )
            )
        if taxable is not None and agi is not None and taxable > agi + 0.02:
            out.append(
                CriticResult.fail(
                    "tax.bounds.taxable",
                    f"Logic Error: taxable_income ({taxable}) cannot exceed AGI ({agi})",
                    fields=["taxable_income", "adjusted_gross_income"],
                )
            )

        owed = fget(data, "amount_owed")
        refund = fget(data, "refund_amount")
        if owed is not None and refund is not None and owed > 0 and refund > 0:
            out.append(
                CriticResult.fail(
                    "tax.mutex.owed_refund",
                    "Logic Error: amount_owed and refund_amount cannot both be positive",
                    fields=["amount_owed", "refund_amount"],
                )
            )
        return out

    def _verify_utility_bill(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)
        prev = fget(data, "previous_balance") or 0.0
        payments = fget(data, "payments_received") or 0.0
        new_charges = fget(data, "new_charges") or 0.0
        due = fget(data, "total_amount_due")
        if due is not None:
            fail = self._eq(
                due,
                prev - payments + new_charges,
                "utility.identity.amount_due",
                "amount_due ≈ previous − payments + new_charges",
                ["total_amount_due", "previous_balance", "payments_received", "new_charges"],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_paystub_legacy(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        scale = scale_from_row(data)
        gross = fget(data, "gross_pay") or 0.0
        taxes = fget(data, "total_taxes") or 0.0
        deductions = fget(data, "total_deductions") or 0.0
        net = fget(data, "net_pay")
        if net is not None:
            fail = self._eq(
                net,
                gross - taxes - deductions,
                "paystub.identity.net",
                "net ≈ gross − taxes − deductions",
                ["net_pay", "gross_pay", "total_taxes", "total_deductions"],
                scale=scale,
            )
            if fail:
                out.append(fail)
        return out

    def _verify_clinical_note(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        hr = fget(data, "heart_rate")
        if hr is not None and not (0 < hr < 300):
            out.append(
                CriticResult.fail(
                    "clinical.bounds.heart_rate",
                    f"Logic Error: Heart rate {hr} is outside physiologically possible bounds.",
                    fields=["heart_rate"],
                    actual=hr,
                )
            )
        return out

    def _verify_lab_result(self, data: Row) -> List[CriticResult]:
        out: List[CriticResult] = []
        bp = data.get("blood_pressure")
        if bp is not None:
            if "/" not in str(bp):
                out.append(
                    CriticResult.fail(
                        "lab.format.blood_pressure",
                        f"Logic Error: Blood pressure ({bp}) must be Systolic/Diastolic.",
                        fields=["blood_pressure"],
                    )
                )
                return out
            parts = str(bp).split("/")
            if len(parts) == 2:
                try:
                    sys, dia = float(parts[0]), float(parts[1])
                except ValueError:
                    out.append(
                        CriticResult.fail(
                            "lab.format.blood_pressure",
                            f"Logic Error: Blood pressure ({bp}) is not numeric.",
                            fields=["blood_pressure"],
                        )
                    )
                    return out
                if not (50 < sys < 250 and 30 < dia < 150):
                    out.append(
                        CriticResult.fail(
                            "lab.bounds.blood_pressure",
                            f"Logic Error: Blood pressure {sys}/{dia} out of safe bounds.",
                            fields=["blood_pressure"],
                        )
                    )
        return out

    def _ground_row(self, schema_name: str, data: Row, source_text: str) -> List[CriticResult]:
        if not source_text or not str(source_text).strip():
            return []
        fields = self._pack_grounding.get(schema_name, ())
        scale = scale_from_row(data)
        out: List[CriticResult] = []
        for key in fields:
            if key not in data or data[key] is None:
                continue
            if fget(data, key) is None:
                continue
            if not value_grounded_in_source(data[key], source_text, scale=scale):
                import os

                sev = (
                    Severity.HARD
                    if os.environ.get("PRISM_GROUNDING_HARD", "").strip() in ("1", "true", "yes")
                    else Severity.SOFT
                )
                out.append(
                    CriticResult.fail(
                        f"grounding.value_not_in_source.{key}",
                        f"Logic Error: value for {key}={data[key]!r} not found in source text",
                        fields=[key],
                        severity=sev,
                        actionable_hint=f"Re-read source digits for {key}; do not invent totals.",
                    )
                )
        return out

    def is_financial_schema(self, schema_name: str) -> bool:
        return schema_name in FINANCIAL_SCHEMAS

    def verify_detailed(
        self,
        schema_name: str,
        extracted_data: Row,
        *,
        source_text: str = "",
    ) -> List[CriticResult]:
        if not extracted_data:
            return []

        logger.info("Running CriticAgent verification", schema_name=schema_name, critic_version=CRITIC_VERSION)

        results: List[CriticResult] = []
        pack_rules = self._pack_rules.get(schema_name) or []
        if pack_rules:
            results.extend(eval_pack_rules(pack_rules, extracted_data))

        pack_hard_completeness = any(
            (not r.ok and r.severity == Severity.HARD and "completeness" in r.rule_id)
            for r in results
        )
        if not pack_hard_completeness:
            if schema_name in self._row_detailed:
                results.extend(self._row_detailed[schema_name](extracted_data))
            else:
                schema_lower = (schema_name or "").lower()
                matched = False
                for keyword, fn in self._row_detailed.items():
                    if keyword in schema_lower and keyword not in FINANCIAL_SCHEMAS:
                        results.extend(fn(extracted_data))
                        matched = True
                        break
                if not matched and schema_name in FINANCIAL_SCHEMAS and not pack_rules:
                    results.append(
                        CriticResult.fail(
                            "critic.missing_registration",
                            f"No critic registered for financial schema '{schema_name}'",
                            fields=[],
                        )
                    )

        results.extend(self._ground_row(schema_name, extracted_data, source_text))
        if extracted_data.get("_related"):
            results.extend(attach_related_and_verify(schema_name, [extracted_data]))
        return results

    def verify(self, schema_name: str, extracted_data: Row) -> Tuple[bool, str]:
        return self._collapse(self.verify_detailed(schema_name, extracted_data))

    def verify_document_detailed(
        self, schema_name: str, rows: List[Row], *, source_text: str = ""
    ) -> List[CriticResult]:
        if not rows:
            return []

        if schema_name in self._doc_detailed:
            results = self._doc_detailed[schema_name](rows)
        elif schema_name in self._row_detailed:
            results = []
            for i, row in enumerate(rows):
                for r in self._row_detailed[schema_name](row):
                    if not r.ok:
                        r.message = f"row {i}: {r.message}"
                        results.append(r)
        elif schema_name in FINANCIAL_SCHEMAS and schema_name not in self._pack_rules:
            results = [
                CriticResult.fail(
                    "critic.missing_doc_registration",
                    f"No document critic for financial schema '{schema_name}'",
                )
            ]
        else:
            results = []
        results.extend(attach_related_and_verify(schema_name, rows))

        if source_text and rows:
            results.extend(self._ground_row(schema_name, rows[0], source_text))
        return results

    def verify_document(self, schema_name: str, rows: List[Row]) -> Tuple[bool, str]:
        return self._collapse(self.verify_document_detailed(schema_name, rows))

    def annotate_meta(
        self, meta: Dict[str, Any], results: List[CriticResult]
    ) -> Dict[str, Any]:
        """Merge structured critic payload into row unmapped meta."""
        payload = results_to_meta(results)
        meta = dict(meta or {})
        hard = merge_results([r for r in results if not r.ok and r.severity == Severity.HARD])
        soft = merge_results([r for r in results if not r.ok and r.severity == Severity.SOFT])
        if not hard.ok:
            meta["critic_error"] = hard.as_error_string()
            meta["row_status"] = "FAILED_VERIFICATION"
        elif not soft.ok:
            meta["critic_error"] = soft.as_error_string()
            meta.setdefault("row_status", "NEEDS_REVIEW")
        meta["critic_results"] = payload.get("critic_results", [])
        meta["critic_version"] = CRITIC_VERSION
        meta["hard_failures"] = payload.get("hard_failures", [])
        meta["soft_failures"] = payload.get("soft_failures", [])
        return meta


def effective_min_tol(scale: float) -> float:
    if scale >= 1_000_000:
        return 0.5
    if scale >= 1_000:
        return 0.1
    return 0.02


__all__ = [
    "CriticAgent",
    "FINANCIAL_SCHEMAS",
    "CRITIC_VERSION",
    "CriticResult",
    "Severity",
    "merge_results",
    "results_to_meta",
]
