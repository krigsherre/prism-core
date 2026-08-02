import pytest
from unittest.mock import MagicMock, patch
from core.dom.chunker import SmartChunker
from config.settings import settings

@patch("core.dom.chunker.fitz")
def test_calculate_chunks_basic(mock_fitz):
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 5
    
    mock_page = MagicMock()
    mock_page.rect.height = 1000
    mock_page.find_tables.return_value = None
    mock_page.get_text.return_value = {"blocks": []}
    mock_doc.load_page.return_value = mock_page
    
    mock_fitz.open.return_value = mock_doc
    
    chunks = SmartChunker.calculate_chunks("dummy.pdf", static_chunk_size=2)
    
    assert len(chunks) == 3
    assert chunks[0]["start_page"] == 0
    assert chunks[0]["end_page"] == 1
    assert chunks[1]["start_page"] == 2
    assert chunks[1]["end_page"] == 3
    assert chunks[2]["start_page"] == 4
    assert chunks[2]["end_page"] == 4

@patch("core.dom.chunker.fitz")
def test_calculate_chunks_with_table_spanning(mock_fitz):
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 4
    
    mock_page_0_1 = MagicMock()
    mock_page_0_1.rect.height = 1000
    
    mock_tables_span = MagicMock()
    mock_tab1 = MagicMock()
    mock_tab1.bbox = [0, 0, 100, 950]
    mock_tables_span.tables = [mock_tab1]
    
    mock_page_0_1.find_tables.return_value = mock_tables_span
    mock_page_0_1.get_text.return_value = {"blocks": []}

    mock_page_2 = MagicMock()
    mock_page_2.rect.height = 1000
    
    mock_tables_cont = MagicMock()
    mock_tab2 = MagicMock()
    mock_tab2.bbox = [0, 50, 100, 200] 
    mock_tables_cont.tables = [mock_tab2]
    
    mock_page_2.find_tables.return_value = mock_tables_cont
    mock_page_2.get_text.return_value = {"blocks": []}
    
    def side_effect(page_num):
        if page_num in [0, 1]:
            return mock_page_0_1
        return mock_page_2
        
    mock_doc.load_page.side_effect = side_effect
    mock_fitz.open.return_value = mock_doc
    
    chunks = SmartChunker.calculate_chunks("dummy.pdf", static_chunk_size=2)
    
    assert len(chunks) == 2
    assert chunks[0]["start_page"] == 0
    assert chunks[0]["end_page"] == 2
    assert chunks[1]["start_page"] == 3
    assert chunks[1]["end_page"] == 3

@patch("core.dom.chunker.fitz")
def test_calculate_chunks_context_injection(mock_fitz):
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 3
    
    mock_page = MagicMock()
    mock_page.rect.height = 1000
    mock_page.find_tables.return_value = None
    mock_page.get_text.return_value = {
        "blocks": [{
            "lines": [{
                "spans": [{
                    "size": 14,
                    "font": "Arial-Bold",
                    "text": "Header Section"
                }]
            }]
        }]
    }
    
    mock_doc.load_page.return_value = mock_page
    mock_fitz.open.return_value = mock_doc
    
    chunks = SmartChunker.calculate_chunks("dummy.pdf", static_chunk_size=2)
    
    assert len(chunks) == 2
    assert chunks[0]["start_page"] == 0
    assert chunks[0]["end_page"] == 1
    assert chunks[0]["injected_context"] == ""
    
    assert chunks[1]["start_page"] == 2
    assert chunks[1]["end_page"] == 2
    assert chunks[1]["injected_context"] == "Header Section"
