import pytest
from core.service import ExtractionService
from unittest.mock import MagicMock, patch

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
@patch("core.service.Image")
@patch("core.service.fitz")
@patch("core.service.os.remove")
async def test_process_document(mock_remove, mock_fitz, mock_image):
    mock_s3 = MagicMock()
    mock_preprocessor = MagicMock()
    mock_preprocessor.preprocess.return_value = ("/tmp/mock.pdf", "PDF_LAYOUT")

    mock_slicer = MagicMock()
    mock_slicer.slice_page.return_value = [{"type": "TEXT", "bbox": [0, 0, 10, 10]}]

    mock_factory = MagicMock()
    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = "Mocked Extracted Text"
    mock_factory.get_extractor.return_value = mock_extractor

    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 1
    mock_page = MagicMock()
    mock_pix = MagicMock()
    mock_pix.width = 100
    mock_pix.height = 100
    mock_pix.samples = b"RGB" * 3333
    mock_page.get_pixmap.return_value = mock_pix
    mock_doc.load_page.return_value = mock_page
    mock_fitz.open.return_value = mock_doc

    mock_post_processor = MagicMock()
    mock_post_processor.process.return_value = "Final DOM"

    service = ExtractionService(
        s3_client=mock_s3,
        preprocessor=mock_preprocessor,
        layout_slicer=mock_slicer,
        extractor_factory=mock_factory,
        post_processor=mock_post_processor,
    )

    result = await service.process_document("s3://test-bucket/test.pdf")
    assert result == "Final DOM"
    mock_s3.download_file.assert_called_once()
    mock_slicer.slice_page.assert_called()
    mock_extractor.extract.assert_called()
    assert mock_remove.call_count >= 1
