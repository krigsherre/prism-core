import pytest
from consumers.graph_consumer import GraphConsumer


def test_graph_consumer_high_signal_filter():
    """Verify high-signal text filtering to control Neo4j ingestion volume."""
    consumer = GraphConsumer()

    rpt_text = "Note 34: Related Party Transactions with Reliance Retail Limited during FY24."
    subsidiary_text = "List of Subsidiaries and Joint Ventures as of March 31, 2024."
    director_text = "Appointment of Independent Directors and Key Managerial Personnel."
    debt_text = "Term loan borrowing and credit facility agreement with State Bank of India."

    assert consumer._is_high_signal_text(rpt_text) is True
    assert consumer._is_high_signal_text(subsidiary_text) is True
    assert consumer._is_high_signal_text(director_text) is True
    assert consumer._is_high_signal_text(debt_text) is True

    generic_text = "Thank you for attending the Annual General Meeting. Welcome to our report."
    short_text = "Page 14"

    assert consumer._is_high_signal_text(generic_text) is False
    assert consumer._is_high_signal_text(short_text) is False


def test_entity_canonicalization():
    """Verify entity name normalization to prevent Neo4j node duplication."""
    consumer = GraphConsumer()

    assert consumer._canonicalize_entity(" Reliance Industries Ltd. ") == "RELIANCE INDUSTRIES LTD"
    assert consumer._canonicalize_entity("Apple Inc,") == "APPLE INC"
    assert consumer._canonicalize_entity("") == ""
