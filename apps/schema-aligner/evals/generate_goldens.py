#!/usr/bin/env python3
"""Generate diverse financial golden fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

OUT = Path(__file__).parent / "golden"


def _write(name: str, payload: Dict[str, Any]) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.name}")


def _pass(
    doc_id: str,
    table: str,
    row: Dict[str, Any] | None = None,
    *,
    rows: List[Dict[str, Any]] | None = None,
    cells: List[Dict[str, Any]] | None = None,
    relations: List[Dict[str, Any]] | None = None,
) -> None:
    payload: Dict[str, Any] = {
        "document_id": doc_id,
        "target_table": table,
        "predicted_table": table,
        "cells": cells or [],
        "relations": relations or [],
    }
    if rows is not None:
        payload["extracted_rows"] = rows
    else:
        payload["extracted_row"] = row or {}
    _write(doc_id, payload)


def _fail(
    doc_id: str,
    table: str,
    row: Dict[str, Any] | None = None,
    *,
    rows: List[Dict[str, Any]] | None = None,
) -> None:
    payload: Dict[str, Any] = {
        "document_id": doc_id,
        "target_table": table,
        "predicted_table": table,
        "cells": [],
        "relations": [],
        "_expect_critic_fail": True,
    }
    if rows is not None:
        payload["extracted_rows"] = rows
    else:
        payload["extracted_row"] = row or {}
    _write(doc_id, payload)


def _soft_fail(
    doc_id: str,
    table: str,
    row: Dict[str, Any] | None = None,
    *,
    rows: List[Dict[str, Any]] | None = None,
) -> None:
    payload: Dict[str, Any] = {
        "document_id": doc_id,
        "target_table": table,
        "predicted_table": table,
        "cells": [],
        "relations": [],
        "_expect_soft_fail": True,
    }
    if rows is not None:
        payload["extracted_rows"] = rows
    else:
        payload["extracted_row"] = row or {}
    _write(doc_id, payload)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    _pass(
        "bs_globex_fy23_millions",
        "standardized_balance_sheet",
        {
            "period_name": "FY2023",
            "context_entity_name": "Globex",
            "context_currency": "USD",
            "context_scale": "in millions",
            "cash_and_equivalents": 90.0,
            "accounts_receivable": 60.0,
            "inventory": 40.0,
            "total_current_assets": 200.0,
            "property_plant_equipment": 300.0,
            "goodwill_and_intangibles": 50.0,
            "total_assets": 550.0,
            "accounts_payable": 45.0,
            "short_term_debt": 25.0,
            "total_current_liabilities": 80.0,
            "long_term_debt": 170.0,
            "total_liabilities": 250.0,
            "retained_earnings": 100.0,
            "total_shareholders_equity": 300.0,
        },
        cells=[
            {"row_index": 0, "column": "total_assets", "value": 550.0},
            {"row_index": 0, "column": "total_liabilities", "value": 250.0},
            {"row_index": 0, "column": "total_shareholders_equity", "value": 300.0},
        ],
        relations=[{"type": "sum_equals", "left": "total_assets", "right": "L+E"}],
    )
    _pass(
        "bs_eu_style_numbers",
        "standardized_balance_sheet",
        {
            "context_scale": "in thousands",
            "total_assets": "1.234,56",
            "total_liabilities": "500,00",
            "total_shareholders_equity": "734,56",
            "cash_and_equivalents": "200,00",
        },
        cells=[
            {"row_index": 0, "column": "total_assets", "value": 1234.56},
            {"row_index": 0, "column": "total_shareholders_equity", "value": 734.56},
        ],
    )
    _pass(
        "bs_accounting_negatives",
        "standardized_balance_sheet",
        {
            "total_assets": 1000.0,
            "total_liabilities": "(200.00)",
            "total_shareholders_equity": 1200.0,
        },
        cells=[{"row_index": 0, "column": "total_assets", "value": 1000.0}],
    )
    _pass(
        "bs_multi_period_rows",
        "standardized_balance_sheet",
        rows=[
            {
                "period_name": "FY2023",
                "total_assets": 500.0,
                "total_liabilities": 200.0,
                "total_shareholders_equity": 300.0,
            },
            {
                "period_name": "FY2024",
                "total_assets": 700.0,
                "total_liabilities": 300.0,
                "total_shareholders_equity": 400.0,
            },
        ],
        cells=[
            {"row_index": 0, "column": "total_assets", "value": 500.0},
            {"row_index": 1, "column": "total_assets", "value": 700.0},
        ],
    )
    _pass(
        "bs_inr_crores_scale",
        "standardized_balance_sheet",
        {
            "context_currency": "INR",
            "context_scale": "in millions",
            "cash_and_equivalents": 12.5,
            "accounts_receivable": 8.0,
            "inventory": 4.5,
            "total_current_assets": 30.0,
            "total_assets": 100.0,
            "total_liabilities": 40.0,
            "total_shareholders_equity": 60.0,
        },
        cells=[{"row_index": 0, "column": "total_assets", "value": 100.0}],
    )

    _pass(
        "is_globex_fy23",
        "standardized_income_statement",
        {
            "revenue_from_operations": 2000.0,
            "other_income": 50.0,
            "total_revenue": 2050.0,
            "cost_of_goods_sold": 1200.0,
            "gross_profit": 850.0,
            "sg_and_a_expenses": 200.0,
            "r_and_d_expenses": 100.0,
            "operating_expenses": 300.0,
            "ebitda": 600.0,
            "depreciation_and_amortization": 80.0,
            "ebit": 520.0,
            "interest_expense": 40.0,
            "profit_before_tax": 480.0,
            "tax_expense": 120.0,
            "net_income": 360.0,
        },
        cells=[
            {"row_index": 0, "column": "gross_profit", "value": 850.0},
            {"row_index": 0, "column": "net_income", "value": 360.0},
        ],
    )
    _pass(
        "is_ops_revenue_gross_only",
        "standardized_income_statement",
        {
            "revenue_from_operations": 1000.0,
            "cost_of_goods_sold": 400.0,
            "gross_profit": 600.0,
        },
        cells=[{"row_index": 0, "column": "gross_profit", "value": 600.0}],
    )
    _pass(
        "is_paren_interest",
        "standardized_income_statement",
        {
            "revenue_from_operations": 500.0,
            "other_income": 0.0,
            "total_revenue": 500.0,
            "cost_of_goods_sold": 200.0,
            "gross_profit": 300.0,
            "ebit": 150.0,
            "interest_expense": "(20)",
            "profit_before_tax": 170.0,
            "tax_expense": 40.0,
            "net_income": 130.0,
        },
        cells=[{"row_index": 0, "column": "profit_before_tax", "value": 170.0}],
    )
    _pass(
        "is_scaled_millions",
        "standardized_income_statement",
        {
            "context_scale": "in millions",
            "revenue_from_operations": 10.0,
            "other_income": 0.5,
            "total_revenue": 10.5,
            "cost_of_goods_sold": 4.0,
            "gross_profit": 6.5,
            "profit_before_tax": 3.0,
            "tax_expense": 0.75,
            "net_income": 2.25,
        },
        cells=[{"row_index": 0, "column": "net_income", "value": 2.25}],
    )

    _pass(
        "cf_globex_fy23",
        "standardized_cash_flow",
        {
            "net_cash_from_operating_activities": 400.0,
            "capital_expenditure": 120.0,
            "net_cash_from_investing_activities": -150.0,
            "dividends_paid": 30.0,
            "net_cash_from_financing_activities": -80.0,
            "net_change_in_cash": 170.0,
        },
        cells=[{"row_index": 0, "column": "net_change_in_cash", "value": 170.0}],
    )
    _pass(
        "cf_all_outflows",
        "standardized_cash_flow",
        {
            "net_cash_from_operating_activities": -10.0,
            "net_cash_from_investing_activities": -20.0,
            "net_cash_from_financing_activities": -5.0,
            "net_change_in_cash": -35.0,
        },
        cells=[{"row_index": 0, "column": "net_change_in_cash", "value": -35.0}],
    )
    _pass(
        "cf_with_ending_cash_related",
        "standardized_cash_flow",
        {
            "net_cash_from_operating_activities": 100.0,
            "net_cash_from_investing_activities": -30.0,
            "net_cash_from_financing_activities": -20.0,
            "net_change_in_cash": 50.0,
            "cash_at_end": 250.0,
            "beginning_cash": 200.0,
            "_related": {
                "standardized_balance_sheet": [
                    {
                        "cash_and_equivalents": 250.0,
                        "prior_cash_and_equivalents": 200.0,
                        "total_assets": 1000.0,
                        "total_liabilities": 400.0,
                        "total_shareholders_equity": 600.0,
                    }
                ]
            },
        },
        cells=[{"row_index": 0, "column": "cash_at_end", "value": 250.0}],
    )

    _pass(
        "bank_header_fees_interest",
        "bank_statement_headers",
        {
            "opening_balance": 5000.0,
            "total_deposits": 1200.0,
            "total_withdrawals": 800.0,
            "total_fees": 25.0,
            "total_interest": 15.0,
            "closing_balance": 5390.0,
        },
        cells=[{"row_index": 0, "column": "closing_balance", "value": 5390.0}],
    )
    _pass(
        "bank_tx_running_ok",
        "bank_statement_transactions",
        rows=[
            {"deposit_amount": 200.0, "withdrawal_amount": None, "balance": 1200.0},
            {"deposit_amount": None, "withdrawal_amount": 50.0, "balance": 1150.0},
            {"deposit_amount": 25.0, "withdrawal_amount": None, "balance": 1175.0},
        ],
        cells=[
            {"row_index": 0, "column": "balance", "value": 1200.0},
            {"row_index": 2, "column": "balance", "value": 1175.0},
        ],
    )
    _pass(
        "bank_header_alt_keys",
        "bank_statement_headers",
        {
            "beginning_balance": 100.0,
            "ending_balance": 150.0,
            "total_deposits": 80.0,
            "total_withdrawals": 30.0,
        },
        cells=[{"row_index": 0, "column": "ending_balance", "value": 150.0}],
    )
    _pass(
        "bank_cross_header_tx_ok",
        "bank_statement_headers",
        {
            "opening_balance": 1000.0,
            "total_deposits": 100.0,
            "total_withdrawals": 50.0,
            "closing_balance": 1050.0,
            "_related": {
                "bank_statement_transactions": [
                    {"deposit_amount": 100.0, "balance": 1100.0},
                    {"withdrawal_amount": 50.0, "balance": 1050.0},
                ]
            },
        },
        cells=[{"row_index": 0, "column": "closing_balance", "value": 1050.0}],
    )

    _pass(
        "invoice_with_discount_shipping",
        "vendor_invoice_headers",
        {
            "invoice_number": "INV-2002",
            "subtotal_amount": 250.0,
            "tax_amount": 20.0,
            "discount_amount": 10.0,
            "shipping_amount": 5.0,
            "total_amount": 265.0,
            "amount_paid": 65.0,
            "amount_due": 200.0,
        },
        cells=[
            {"row_index": 0, "column": "total_amount", "value": 265.0},
            {"row_index": 0, "column": "amount_due", "value": 200.0},
        ],
    )
    _pass(
        "invoice_line_qty_price",
        "invoice_line_items",
        rows=[
            {
                "description": "Widget",
                "quantity": 10.0,
                "unit_price": 5.0,
                "discount_amount": 0.0,
                "tax_amount": 2.0,
                "total_amount": 52.0,
            },
            {
                "description": "Gadget",
                "quantity": 2.0,
                "unit_price": 40.0,
                "discount_amount": 5.0,
                "tax_amount": 0.0,
                "total_amount": 75.0,
            },
        ],
        cells=[
            {"row_index": 0, "column": "total_amount", "value": 52.0},
            {"row_index": 1, "column": "total_amount", "value": 75.0},
        ],
    )
    _pass(
        "invoice_header_lines_match",
        "vendor_invoice_headers",
        {
            "subtotal_amount": 100.0,
            "tax_amount": 10.0,
            "total_amount": 110.0,
            "amount_due": 110.0,
            "amount_paid": 0.0,
            "_related": {
                "invoice_line_items": [
                    {"quantity": 2, "unit_price": 30, "total_amount": 60},
                    {"quantity": 1, "unit_price": 40, "total_amount": 40},
                ]
            },
        },
        cells=[{"row_index": 0, "column": "subtotal_amount", "value": 100.0}],
    )
    _pass(
        "po_header_simple",
        "purchase_order_headers",
        {
            "po_number": "PO-88",
            "subtotal_amount": 1000.0,
            "tax_amount": 50.0,
            "total_value": 1050.0,
            "currency": "USD",
        },
        cells=[{"row_index": 0, "column": "total_value", "value": 1050.0}],
    )
    _pass(
        "po_line_item",
        "purchase_order_line_items",
        {
            "item_code": "SKU-1",
            "quantity": 5.0,
            "unit_price": 20.0,
            "discount_amount": 0.0,
            "tax_amount": 0.0,
            "total_price": 100.0,
        },
        cells=[{"row_index": 0, "column": "total_price", "value": 100.0}],
    )
    _pass(
        "receipt_header_simple",
        "receipt_headers",
        {
            "subtotal": 45.0,
            "tax_amount": 5.0,
            "total_amount": 50.0,
        },
        cells=[{"row_index": 0, "column": "total_amount", "value": 50.0}],
    )
    _pass(
        "receipt_line_item",
        "receipt_line_items",
        {
            "quantity": 3.0,
            "unit_price": 4.0,
            "discount_amount": 0.0,
            "tax_amount": 0.5,
            "total_amount": 12.5,
        },
        cells=[{"row_index": 0, "column": "total_amount", "value": 12.5}],
    )

    _pass(
        "tax_w2_bounds_ok",
        "tax_form_headers",
        {
            "social_security_wages": 80000.0,
            "medicare_wages": 85000.0,
            "state_wages": 80000.0,
            "state_income_tax": 4000.0,
            "adjusted_gross_income": 90000.0,
            "total_income": 95000.0,
            "taxable_income": 70000.0,
            "refund_amount": 500.0,
            "amount_owed": 0.0,
        },
        cells=[{"row_index": 0, "column": "medicare_wages", "value": 85000.0}],
    )
    _pass(
        "utility_bill_ok",
        "utility_bills",
        {
            "previous_balance": 100.0,
            "payments_received": 100.0,
            "new_charges": 85.5,
            "total_amount_due": 85.5,
        },
        cells=[{"row_index": 0, "column": "total_amount_due", "value": 85.5}],
    )

    _pass(
        "invoice_currency_symbols",
        "vendor_invoice_headers",
        {
            "subtotal_amount": "$1,000.00",
            "tax_amount": "$80.00",
            "discount_amount": "$0.00",
            "shipping_amount": "$20.00",
            "total_amount": "$1,100.00",
            "amount_paid": "$100.00",
            "amount_due": "$1,000.00",
        },
        cells=[
            {"row_index": 0, "column": "total_amount", "value": 1100.0},
            {"row_index": 0, "column": "amount_due", "value": 1000.0},
        ],
    )
    _pass(
        "bs_dollar_millions_suffix",
        "standardized_balance_sheet",
        {
            "total_assets": "$2.5M",
            "total_liabilities": "$1.0M",
            "total_shareholders_equity": "$1.5M",
        },
        cells=[{"row_index": 0, "column": "total_assets", "value": 2500000.0}],
    )

    _fail(
        "bs_incomplete_missing_equity",
        "standardized_balance_sheet",
        {"total_assets": 700.0, "total_liabilities": 300.0},
    )
    _fail(
        "bs_identity_break_large",
        "standardized_balance_sheet",
        {
            "total_assets": 1000.0,
            "total_liabilities": 400.0,
            "total_shareholders_equity": 400.0,
        },
    )
    _fail(
        "bs_negative_assets",
        "standardized_balance_sheet",
        {
            "total_assets": -10.0,
            "total_liabilities": 0.0,
            "total_shareholders_equity": -10.0,
        },
    )
    _fail(
        "is_net_income_break",
        "standardized_income_statement",
        {
            "profit_before_tax": 200.0,
            "tax_expense": 50.0,
            "net_income": 100.0,
        },
    )
    _fail(
        "is_gross_without_cogs",
        "standardized_income_statement",
        {"gross_profit": 420.0, "total_revenue": 1000.0},
    )
    _fail(
        "cf_incomplete_net_change",
        "standardized_cash_flow",
        {
            "net_change_in_cash": 100.0,
            "net_cash_from_operating_activities": 80.0,
        },
    )
    _fail(
        "cf_identity_break",
        "standardized_cash_flow",
        {
            "net_cash_from_operating_activities": 100.0,
            "net_cash_from_investing_activities": -20.0,
            "net_cash_from_financing_activities": -10.0,
            "net_change_in_cash": 999.0,
        },
    )
    _fail(
        "bank_header_closing_break",
        "bank_statement_headers",
        {
            "opening_balance": 1000.0,
            "total_deposits": 100.0,
            "total_withdrawals": 50.0,
            "closing_balance": 2000.0,
        },
    )
    _fail(
        "bank_header_incomplete",
        "bank_statement_headers",
        {"opening_balance": 1000.0, "closing_balance": 1100.0},
    )
    _fail(
        "bank_tx_running_break",
        "bank_statement_transactions",
        rows=[
            {"deposit_amount": 100.0, "balance": 1100.0},
            {"withdrawal_amount": 50.0, "balance": 2000.0},
        ],
    )
    _fail(
        "bank_tx_both_deposit_withdrawal",
        "bank_statement_transactions",
        rows=[
            {"deposit_amount": 10.0, "withdrawal_amount": 5.0, "balance": 100.0},
        ],
    )
    _fail(
        "invoice_total_break",
        "vendor_invoice_headers",
        {
            "subtotal_amount": 100.0,
            "tax_amount": 10.0,
            "discount_amount": 0.0,
            "shipping_amount": 0.0,
            "total_amount": 50.0,
        },
    )
    _fail(
        "invoice_total_without_subtotal",
        "vendor_invoice_headers",
        {"total_amount": 105.0},
    )
    _fail(
        "invoice_line_missing_qty",
        "invoice_line_items",
        {"unit_price": 10.0, "total_amount": 50.0},
    )
    _fail(
        "invoice_cross_lines_mismatch",
        "vendor_invoice_headers",
        {
            "subtotal_amount": 100.0,
            "tax_amount": 0.0,
            "total_amount": 100.0,
            "_related": {
                "invoice_line_items": [
                    {"total_amount": 30.0},
                    {"total_amount": 30.0},
                ]
            },
        },
    )
    _fail(
        "po_total_break",
        "purchase_order_headers",
        {"subtotal_amount": 100.0, "tax_amount": 10.0, "total_value": 50.0},
    )
    _fail(
        "receipt_total_break",
        "receipt_headers",
        {"subtotal": 40.0, "tax_amount": 5.0, "total_amount": 100.0},
    )
    _fail(
        "utility_due_break",
        "utility_bills",
        {
            "previous_balance": 50.0,
            "payments_received": 50.0,
            "new_charges": 30.0,
            "total_amount_due": 99.0,
        },
    )
    _fail(
        "tax_ss_exceeds_medicare",
        "tax_form_headers",
        {"social_security_wages": 90000.0, "medicare_wages": 80000.0},
    )
    _fail(
        "tax_owed_and_refund",
        "tax_form_headers",
        {"amount_owed": 100.0, "refund_amount": 50.0},
    )
    _fail(
        "bank_cross_closing_mismatch",
        "bank_statement_headers",
        {
            "opening_balance": 1000.0,
            "total_deposits": 100.0,
            "total_withdrawals": 50.0,
            "closing_balance": 1050.0,
            "_related": {
                "bank_statement_transactions": [
                    {"deposit_amount": 100.0, "balance": 1100.0},
                    {"withdrawal_amount": 50.0, "balance": 900.0},
                ]
            },
        },
    )
    _soft_fail(
        "cf_cross_bs_cash_mismatch",
        "standardized_cash_flow",
        {
            "net_cash_from_operating_activities": 50.0,
            "net_cash_from_investing_activities": 0.0,
            "net_cash_from_financing_activities": 0.0,
            "net_change_in_cash": 50.0,
            "cash_at_end": 250.0,
            "_related": {
                "standardized_balance_sheet": [
                    {
                        "cash_and_equivalents": 999.0,
                        "total_assets": 2000.0,
                        "total_liabilities": 1000.0,
                        "total_shareholders_equity": 1000.0,
                    }
                ]
            },
        },
    )

    n = len(list(OUT.glob("*.json")))
    print(f"\nTotal golden fixtures now: {n}")


if __name__ == "__main__":
    main()
