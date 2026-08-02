"""Tests for correction → golden export helpers."""
from utils.corrections import correction_to_golden


def test_correction_to_golden_multi_row():
    golden = correction_to_golden(
        {
            "id": "corr-2",
            "document_id": "doc-bank",
            "target_table": "bank_statement_transactions",
            "after_data": [
                {"deposit_amount": 100, "balance": 1100},
                {"withdrawal_amount": 50, "balance": 1050},
            ],
            "field_patches": [
                {"column": "balance", "before": 1000, "after": 1050, "row_index": 1},
            ],
            "critic_error": "[bank.tx.running_balance] break",
        }
    )
    assert "extracted_rows" in golden
    assert len(golden["extracted_rows"]) == 2
    assert golden["cells"][0]["row_index"] == 1
    assert golden["_correction_id"] == "corr-2"
