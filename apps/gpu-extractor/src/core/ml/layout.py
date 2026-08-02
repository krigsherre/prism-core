from typing import List, Dict, Any, Tuple, Optional, cast
import fitz
import structlog
import httpx
import base64
import io
from PIL import Image
from config.settings import settings

class LayoutSlicer:
    """
    Slices a PDF page into sequenced bounding boxes.
    Implements XY-Cut to handle multi-column layouts properly.
    """
    def __init__(self):
        self.logger = structlog.get_logger(__name__)
        self.endpoint_url = settings.docling_layout_url

    def slice_page(self, page: fitz.Page) -> List[Dict[str, Any]]:
        """
        Returns a list of boxes:
        [{'type': 'TEXT'|'IMAGE'|'TABLE', 'bbox': [x0, y0, x1, y1], 'content': str|None}]
        """
        boxes = []
        if self.endpoint_url:
            boxes = self._attempt_docling_slicing(page)
            
        if not boxes:
            self.logger.warning("Docling API not reached or returned no results, falling back to basic PyMuPDF slicing.")
            boxes = self._pymupdf_fallback_slicing(page)
            
        return self._sort_boxes_reading_order(boxes)


    def _attempt_docling_slicing(self, page: fitz.Page) -> List[Dict[str, Any]]:
        pix = page.get_pixmap(dpi=150)
        b64_image = self._convert_page_to_base64(pix)
        
        results = self._fetch_docling_layout(b64_image)
        if not results:
            return []
            
        return self._parse_docling_results(results, pix, page)

    def _convert_page_to_base64(self, pix: fitz.Pixmap) -> str:
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _fetch_docling_layout(self, b64_image: str) -> Optional[List[Dict[str, Any]]]:
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self.endpoint_url}/layout",
                    json={"image_base64": b64_image, "threshold": 0.3}
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    self.logger.error(f"Layout API Error: {resp.status_code} {resp.text}")
        except Exception as e:
            self.logger.error(f"Failed to call Layout API: {e}")
        return None

    def _parse_docling_results(self, results: List[Dict[str, Any]], pix: fitz.Pixmap, page: fitz.Page) -> List[Dict[str, Any]]:
        boxes = []
        scale_x = page.rect.width / pix.width
        scale_y = page.rect.height / pix.height
        
        for item in results:
            label_name = item["label"]
            x0, y0, x1, y1 = item["bbox"]
            pdf_bbox = [x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y]
            
            b_type, content = self._map_docling_label(label_name, pdf_bbox, page)
            boxes.append({"type": b_type, "bbox": pdf_bbox, "content": content})
            
        return boxes

    def _map_docling_label(self, label_name: str, pdf_bbox: List[float], page: fitz.Page) -> Tuple[str, Optional[str]]:
        rect = fitz.Rect(pdf_bbox)
        
        if label_name == "table":
            return "TABLE", None
        elif label_name in ["picture", "figure"]:
            return "IMAGE", None
            
        text = cast(str, page.get_text("text", clip=rect))
        
        if label_name == "key_value_region":
            return "KEY_VALUE", text
        elif label_name == "form":
            return "FORM", text
        elif label_name == "section_header":
            return "SECTION_HEADER", text
        elif label_name == "title":
            return "TITLE", text
        elif "checkbox" in label_name:
            state = "CHECKED" if "selected" in label_name and "unselected" not in label_name else "UNCHECKED"
            return "CHECKBOX", f"[{state}] {text}"
        elif label_name == "code":
            return "CODE", text
        else:
            return "TEXT", text


    def _pymupdf_fallback_slicing(self, page: fitz.Page) -> List[Dict[str, Any]]:
        boxes = []
        tables = page.find_tables(strategy="text") or []
        table_bboxes = [list(t.bbox) for t in tables]
        
        for bbox in table_bboxes:
            boxes.append({"type": "TABLE", "bbox": bbox, "content": None})
            
        page_dict = cast(Dict[str, Any], page.get_text("dict"))
        blocks = page_dict.get("blocks", [])
        
        for b in blocks:
            b_type = "TEXT" if b.get("type") == 0 else "IMAGE"
            bbox = b.get("bbox")
            
            if self._is_box_inside_table(bbox, table_bboxes):
                continue
                
            content = self._extract_pymupdf_text_content(b) if b_type == "TEXT" else None
            boxes.append({"type": b_type, "bbox": bbox, "content": content})
            
        return boxes

    def _is_box_inside_table(self, bbox: List[float], table_bboxes: List[List[float]]) -> bool:
        for t_bbox in table_bboxes:
            if not (bbox[2] < t_bbox[0] or bbox[0] > t_bbox[2] or bbox[3] < t_bbox[1] or bbox[1] > t_bbox[3]):
                return True
        return False

    def _extract_pymupdf_text_content(self, block: Dict[str, Any]) -> str:
        lines = block.get("lines", [])
        text_content = []
        for line in lines:
            for span in line.get("spans", []):
                text_content.append(span.get("text", ""))
        return " ".join(text_content).strip()


    def _sort_boxes_reading_order(self, boxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Uses a 1D density-based clustering (DBSCAN style) on the Y axis to group
        elements into lines dynamically, handling subscripts and varying font sizes.
        """
        if not boxes:
            return []
            
        sorted_by_y = sorted(boxes, key=lambda b: b['bbox'][1])
        clusters = self._cluster_into_lines(sorted_by_y, eps=15.0)
        
        return self._flatten_and_sort_horizontally(clusters)

    def _cluster_into_lines(self, sorted_by_y: List[Dict[str, Any]], eps: float) -> List[List[Dict[str, Any]]]:
        clusters = []
        current_cluster = [sorted_by_y[0]]
        current_y_mean = sorted_by_y[0]['bbox'][1]
        
        for box in sorted_by_y[1:]:
            y = box['bbox'][1]
            if abs(y - current_y_mean) <= eps:
                current_cluster.append(box)
                current_y_mean = sum(b['bbox'][1] for b in current_cluster) / len(current_cluster)
            else:
                clusters.append(current_cluster)
                current_cluster = [box]
                current_y_mean = y
                
        if current_cluster:
            clusters.append(current_cluster)
            
        return clusters

    def _flatten_and_sort_horizontally(self, clusters: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        sorted_boxes = []
        for cluster in clusters:
            sorted_cluster = sorted(cluster, key=lambda b: b['bbox'][0])
            sorted_boxes.extend(sorted_cluster)
        return sorted_boxes