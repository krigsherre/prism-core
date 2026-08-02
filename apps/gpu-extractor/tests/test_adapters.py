from unittest.mock import patch, MagicMock, AsyncMock
from core.ml.adapters import PyMuPDFAdapter, ExtractorFactory, VLLMAdapter
from PIL import Image

def test_extractor_factory_text():
    factory = ExtractorFactory()
    extractor = factory.get_extractor("TEXT")
    assert isinstance(extractor, PyMuPDFAdapter)

@patch("core.ml.adapters.settings")
@patch("core.ml.adapters.VLLMAdapter")
def test_extractor_factory_lazy_load_vllm(mock_vllm_adapter, mock_settings):
    mock_settings.vllm_paddleocr_url = "http://mock1"
    mock_settings.vllm_docling_url = "http://mock2"
    factory = ExtractorFactory()
    mock_vllm_adapter.assert_not_called()

    extractor = factory.get_extractor("TABLE")
    mock_vllm_adapter.assert_called_once()
    assert extractor == mock_vllm_adapter.return_value

    factory.get_extractor("IMAGE")
    mock_vllm_adapter.assert_called_once()
    extractor_form = factory.get_extractor("FORM")
    assert mock_vllm_adapter.call_count == 2
    assert extractor_form == mock_vllm_adapter.return_value

def test_pymupdf_adapter_extraction():
    adapter = PyMuPDFAdapter()

    mock_page = MagicMock()
    mock_page.get_text.return_value = "Extracted Text"

    text = adapter.extract(mock_page, [0, 0, 100, 100])
    assert text == "Extracted Text"
    mock_page.get_text.assert_called_once()

@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
def test_vllm_adapter_extraction(mock_post):
    adapter = VLLMAdapter("http://fake-url", "fake-model")
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "mocked text output"}}]
    }
    mock_post.return_value = mock_response

    img = Image.new('RGB', (10, 10), color='white')
    text = adapter.extract(img)
    
    assert text == "mocked text output"
    mock_post.assert_called_once()
