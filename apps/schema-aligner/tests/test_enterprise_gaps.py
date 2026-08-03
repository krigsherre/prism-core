import pytest
from core.mca_xbrl_parser import is_mca_xbrl_content, parse_mca_xbrl_facts
from core.doc_router import extract_entity_identifiers
from core.fx_converter import convert_currency, get_fx_rate


def test_mca_xbrl_parser():
    """Verify Indian MCA Ind AS XBRL XML parsing."""
    sample_xml = '<ind-as:RevenueFromOperations>50000000</ind-as:RevenueFromOperations>'
    assert is_mca_xbrl_content(sample_xml) is True

    facts = parse_mca_xbrl_facts(sample_xml)
    assert facts.get("RevenueFromOperations") == "50000000"


def test_extract_entity_identifiers():
    """Verify CIN, CIK, Ticker, and NSE Symbol extraction."""
    indian_doc = "Reliance Industries Ltd. CIN: L17110MH1973PLC019786 NSE: RELIANCE"
    ids_ind = extract_entity_identifiers(indian_doc)
    assert ids_ind["cin"] == "L17110MH1973PLC019786"
    assert ids_ind["nse_symbol"] == "RELIANCE"

    us_doc = "Apple Inc. CIK: 0000320193 Ticker: AAPL"
    ids_us = extract_entity_identifiers(us_doc)
    assert ids_us["cik"] == "0000320193"
    assert ids_us["ticker"] == "AAPL"


def test_fx_converter():
    """Verify multi-currency conversion."""
    inr_amt = convert_currency(100.0, "USD", "INR")
    assert inr_amt == 8350.0

    usd_amt = convert_currency(8350.0, "INR", "USD")
    assert usd_amt == 100.0

    rate = get_fx_rate("EUR", "USD")
    assert rate > 0.0
