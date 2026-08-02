import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import Tuple
import tempfile


from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential


class FormatStrategy(ABC):
    @abstractmethod
    def handle(self, file_path: str) -> Tuple[str, str]:
        pass


class PdfFormatStrategy(FormatStrategy):
    def handle(self, file_path: str) -> Tuple[str, str]:
        return file_path, "PDF_LAYOUT"


class SpreadsheetFormatStrategy(FormatStrategy):
    def handle(self, file_path: str) -> Tuple[str, str]:
        return file_path, "PANDAS_TABLE"


class ImageFormatStrategy(FormatStrategy):
    def handle(self, file_path: str) -> Tuple[str, str]:
        return file_path, "VLM_IMAGE"


class RawTextFormatStrategy(FormatStrategy):
    def handle(self, file_path: str) -> Tuple[str, str]:
        return file_path, "RAW_TEXT"


class GotenbergFormatStrategy(FormatStrategy):
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call_gotenberg(self, file_path: str, pdf_path: str):
        import subprocess
        subprocess.run([
            "curl", "--request", "POST", 
            "--url", settings.gotenberg_url, 
            "--header", "Content-Type: multipart/form-data", 
            "--form", f"files=@{file_path}",
            "-o", pdf_path,
            "--silent"
        ], check=True)

    def handle(self, file_path: str) -> Tuple[str, str]:
        """
        Sends the document to a stateless Gotenberg sidecar for PDF conversion,
        bypassing the need for a heavy local LibreOffice installation.
        """
        try:
            
            outdir = tempfile.gettempdir()
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            pdf_path = os.path.join(outdir, f"{base_name}.pdf")
            
            self._call_gotenberg(file_path, pdf_path)
            
            if os.path.exists(pdf_path):
                return pdf_path, "PDF_LAYOUT"
        except Exception as e:
            import structlog
            logger = structlog.get_logger(__name__)
            logger.error(f"Failed to convert {file_path} to PDF via Gotenberg: {e}")

        return file_path, "RAW_TEXT"


class OmniPreprocessor:
    """
    Context class for the Strategy Pattern.
    """

    def __init__(self):
        self.strategies = {
            "application/pdf": PdfFormatStrategy(),
            "application/vnd.ms-excel": SpreadsheetFormatStrategy(),
            "text/csv": SpreadsheetFormatStrategy(),
            "image/jpeg": ImageFormatStrategy(),
            "image/png": ImageFormatStrategy(),
            "text/plain": RawTextFormatStrategy(),
            "application/msword": GotenbergFormatStrategy(),
            "application/vnd.ms-powerpoint": GotenbergFormatStrategy(),
        }

    def _get_mime_type(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".pdf"]:
            return "application/pdf"
        elif ext in [".xlsx", ".xls"]:
            return "application/vnd.ms-excel"
        elif ext in [".csv"]:
            return "text/csv"
        elif ext in [".docx", ".doc"]:
            return "application/msword"
        elif ext in [".pptx", ".ppt"]:
            return "application/vnd.ms-powerpoint"
        elif ext in [".png", ".jpg", ".jpeg"]:
            return "image/jpeg"
        elif ext in [".txt", ".md", ".html"]:
            return "text/plain"
        return "application/octet-stream"

    def preprocess(self, file_path: str) -> Tuple[str, str]:
        mime = self._get_mime_type(file_path)
        strategy = self.strategies.get(mime, PdfFormatStrategy())
        return strategy.handle(file_path)
