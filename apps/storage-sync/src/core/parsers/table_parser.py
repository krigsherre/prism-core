import json
import re
from typing import Any, Dict, List


class TableParser:
    """
    Domain service for parsing, converting, and formatting tabular data structures.
    Supports PaddleOCR-VL OTSL, markdown tables, JSON columnar structures, and key-value formats.
    """

    _OTSL_MARKERS = ("<fcel>", "<nl>", "<ecel>", "<lcel>", "<ucel>")
    _CELL_SPLIT_REGEX = re.compile(r"<fcel>|<lcel>|<ucel>")

    @classmethod
    def is_otsl(cls, content: str) -> bool:
        """Check if content contains PaddleOCR-VL OTSL markers."""
        if not content:
            return False
        return any(marker in content for marker in cls._OTSL_MARKERS)

    @classmethod
    def headers_rows_to_columnar(cls, headers: List[Any], rows: List[List[Any]]) -> Dict[str, List[str]]:
        """Transform header list and row tuples into a columnar dictionary of arrays."""
        result: Dict[str, List[str]] = {str(h): [] for h in headers}
        for row in rows:
            for i, h in enumerate(headers):
                cell = str(row[i]) if i < len(row) else ""
                result[str(h)].append(cell)
        return result

    @classmethod
    def parse_otsl(cls, content: str) -> Dict[str, List[str]]:
        """Parse PaddleOCR-VL OTSL markup into columnar dictionary format."""
        cleaned = content.strip().replace("<ecel>", "")
        row_strs = [r for r in cleaned.split("<nl>") if r.strip()]

        parsed_rows: List[List[str]] = []
        for row_str in row_strs:
            cells = cls._CELL_SPLIT_REGEX.split(row_str)
            if cells and cells[0] == "" and len(cells) > 1:
                cells = cells[1:]
            cells = [c.strip() for c in cells]
            if cells:
                parsed_rows.append(cells)

        if not parsed_rows:
            return {}

        headers = parsed_rows[0]
        data_rows = parsed_rows[1:] if len(parsed_rows) > 1 else []
        width = len(headers)
        normalized: List[List[str]] = []
        for row in data_rows:
            if len(row) < width:
                row = row + [""] * (width - len(row))
            elif len(row) > width:
                row = row[:width]
            normalized.append(row)
        return cls.headers_rows_to_columnar(headers, normalized)

    @classmethod
    def looks_like_kv_lines(cls, content: str) -> bool:
        """Determine if multi-line content resembles Key: Value lines."""
        if cls.is_otsl(content):
            return False
        lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
        if len(lines) < 1:
            return False
        if len(lines) == 1 and ("=" in lines[0] or len(lines[0]) > 200):
            return False
        kvish = 0
        for line in lines:
            if ": " in line or (line.count(":") == 1 and "=" not in line):
                kvish += 1
        return kvish >= max(1, len(lines) // 2)

    @classmethod
    def parse_table_content(cls, content: str) -> Dict[str, Any]:
        """
        Universal table content parser. Handles JSON, OTSL, Markdown tables, and KV strings.
        """
        if not content:
            return {}

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                if "headers" in parsed and "rows" in parsed:
                    headers = [str(h) for h in parsed["headers"]]
                    rows = parsed.get("rows") or []
                    columnar = cls.headers_rows_to_columnar(headers, rows)
                    if isinstance(parsed.get("_structure"), dict):
                        columnar["_structure"] = parsed["_structure"]
                    return columnar
                data_keys = {k: v for k, v in parsed.items() if not str(k).startswith("_")}
                if data_keys and all(isinstance(v, list) for v in data_keys.values()):
                    out = dict(data_keys)
                    if isinstance(parsed.get("_structure"), dict):
                        out["_structure"] = parsed["_structure"]
                    return out
                if cls.is_otsl(content) or any(
                    cls.is_otsl(str(k)) or cls.is_otsl(str(v)) for k, v in parsed.items()
                ):
                    parts = []
                    for k, v in parsed.items():
                        parts.append(str(k))
                        if isinstance(v, str):
                            parts.append(v)
                    return cls.parse_otsl("".join(parts))
                if parsed and all(not isinstance(v, (list, dict)) for v in parsed.values()):
                    return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        if cls.is_otsl(content):
            return cls.parse_otsl(content)

        lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
        if not lines:
            return {}

        result: Dict[str, List[str]] = {}
        header_idx = -1
        for i, line in enumerate(lines):
            if "|" in line and (i + 1 < len(lines) and "---" in lines[i + 1]):
                header_idx = i
                break

        if header_idx == -1:
            for i, line in enumerate(lines):
                if "|" in line and len(line.split("|")) > 1:
                    header_idx = i
                    break

        if header_idx != -1:
            raw_headers = lines[header_idx].split("|")
            if raw_headers and raw_headers[0].strip() == "":
                raw_headers = raw_headers[1:]
            if raw_headers and raw_headers[-1].strip() == "":
                raw_headers = raw_headers[:-1]

            headers = []
            for i, h in enumerate(raw_headers):
                clean_h = h.strip()
                if not clean_h:
                    clean_h = f"col_{i}"
                headers.append(clean_h)

            for h in headers:
                result[h] = []

            if header_idx + 1 < len(lines) and "---" in lines[header_idx + 1]:
                data_lines = lines[header_idx + 2 :]
            else:
                data_lines = lines[header_idx + 1 :]

            for line in data_lines:
                if "|" not in line:
                    continue
                parts = line.split("|")
                if parts and parts[0].strip() == "":
                    parts = parts[1:]
                if parts and parts[-1].strip() == "":
                    parts = parts[:-1]

                cells = [c.strip() for c in parts]
                for i, h in enumerate(headers):
                    if i < len(cells):
                        result[h].append(cells[i])
                    else:
                        result[h].append("")

            if result and any(any(str(v).strip() for v in arr) for arr in result.values()):
                return result

        if cls.looks_like_kv_lines(content):
            from core.parsers.kv_parser import KeyValueParser
            kv_res = KeyValueParser.parse(content)
            if kv_res and any(v != "" for v in kv_res.values()):
                return kv_res

        return {f"header_{i+1}": line for i, line in enumerate(lines)}

    @classmethod
    def dict_to_markdown_table(cls, data: Dict[str, Any]) -> str:
        """Converts a flat dictionary of arrays into a Markdown table for semantic RAG."""
        if not data:
            return ""
        keys = [k for k in data.keys() if not str(k).startswith("_")]
        if not keys:
            return ""

        if all(not isinstance(data[k], list) for k in keys):
            md = "| " + " | ".join(keys) + " |\n"
            md += "|" + "|".join(["---" for _ in keys]) + "|\n"
            row = [str(data[k]).replace("|", "\\|").replace("\n", " ") for k in keys]
            md += "| " + " | ".join(row) + " |\n"
            return md.strip()

        md = "| " + " | ".join(keys) + " |\n"
        md += "|" + "|".join(["---" for _ in keys]) + "|\n"
        max_len = max([len(data[k]) if isinstance(data[k], list) else 1 for k in keys])
        for i in range(max_len):
            row = []
            for k in keys:
                arr = data[k]
                if isinstance(arr, list):
                    val = arr[i] if i < len(arr) else ""
                else:
                    val = arr if i == 0 else ""
                row.append(str(val).replace("|", "\\|").replace("\n", " "))
            md += "| " + " | ".join(row) + " |\n"

        return md.strip()

    @classmethod
    def columnar_to_headers_rows_json(cls, data: Dict[str, Any]) -> str:
        """Transforms columnar dictionary into JSON string with explicit headers and rows arrays."""
        headers = list(data.keys())
        if not headers:
            return json.dumps({"headers": [], "rows": []})
        max_len = max((len(v) if isinstance(v, list) else 1) for v in data.values())
        rows = []
        for i in range(max_len):
            row = []
            for h in headers:
                arr = data[h]
                if isinstance(arr, list):
                    row.append(str(arr[i]) if i < len(arr) else "")
                else:
                    row.append(str(arr) if i == 0 else "")
            rows.append(row)
        return json.dumps({"headers": headers, "rows": rows}, ensure_ascii=False)
