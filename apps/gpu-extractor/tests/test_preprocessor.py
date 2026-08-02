from core.dom.preprocessor import OmniPreprocessor

def test_preprocess_pdf():
    preprocessor = OmniPreprocessor()
    path, directive = preprocessor.preprocess("test.pdf")
    assert path == "test.pdf"
    assert directive == "PDF_LAYOUT"


def test_preprocess_spreadsheet():
    preprocessor = OmniPreprocessor()
    path, directive = preprocessor.preprocess("financials.xlsx")
    assert path == "financials.xlsx"
    assert directive == "PANDAS_TABLE"


def test_preprocess_csv():
    preprocessor = OmniPreprocessor()
    path, directive = preprocessor.preprocess("data.csv")
    assert path == "data.csv"
    assert directive == "PANDAS_TABLE"


def test_preprocess_image():
    preprocessor = OmniPreprocessor()
    path, directive = preprocessor.preprocess("scan.png")
    assert path == "scan.png"
    assert directive == "VLM_IMAGE"


def test_preprocess_raw_text():
    preprocessor = OmniPreprocessor()
    path, directive = preprocessor.preprocess("README.md")
    assert path == "README.md"
    assert directive == "RAW_TEXT"
