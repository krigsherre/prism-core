from core.ml.layout import LayoutSlicer
from unittest.mock import MagicMock


def test_layout_slicer_pymupdf_fallback():
    slicer = LayoutSlicer()
    mock_page = MagicMock()
    mock_pix = MagicMock()
    mock_pix.width = 100
    mock_pix.height = 100
    mock_pix.samples = b"\xff" * (100 * 100 * 3)
    mock_page.get_pixmap.return_value = mock_pix
    mock_page.rect.width = 100
    mock_page.rect.height = 100
    mock_page.get_text.return_value = {
        "blocks": [
            {
                "type": 0,
                "bbox": [10, 10, 100, 20],
                "lines": [{"spans": [{"text": "Hello"}, {"text": "World"}]}],
            },
            {"type": 1, "bbox": [10, 30, 100, 100]}, 
        ]
    }

    boxes = slicer.slice_page(mock_page)

    assert len(boxes) == 2
    assert boxes[0]["type"] == "TEXT"
    assert boxes[0]["content"] == "Hello World"
    assert boxes[0]["bbox"] == [10, 10, 100, 20]

    assert boxes[1]["type"] == "IMAGE"
    assert boxes[1]["content"] is None
    assert boxes[1]["bbox"] == [10, 30, 100, 100]
