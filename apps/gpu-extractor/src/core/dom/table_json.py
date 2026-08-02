"""Normalize PaddleOCR / VLM table output into canonical JSON.

Canonical form:
  {"headers": ["col1", ...], "rows": [["v1", ...], ...]}
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class TableJSON(BaseModel):
    headers: List[str] = Field(default_factory=list, description="Column header labels")
    rows: List[List[str]] = Field(default_factory=list, description="Data rows as arrays of cell strings")


_OTSL_CELL_SPLIT = re.compile(r"<fcel>|<lcel>|<ucel>|<ecel>")
_OTSL_MARKERS = ("<fcel>", "<nl>", "<ecel>", "<lcel>", "<ucel>")


def is_otsl(text: str) -> bool:
    return any(m in text for m in _OTSL_MARKERS)


def parse_otsl(text: str) -> TableJSON:
    """Parse PaddleOCR-VL OTSL (Optimized Table Structure Language) into TableJSON."""
    cleaned = text.strip()
    if cleaned.startswith("{") and "<fcel>" in cleaned:
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict) and len(obj) == 1:
                k, v = next(iter(obj.items()))
                cleaned = f"{k}{v}" if isinstance(v, str) else k
            elif isinstance(obj, str):
                cleaned = obj
        except (json.JSONDecodeError, TypeError):
            pass

    cleaned = cleaned.replace("<ecel>", "")
    row_strs = [r for r in cleaned.split("<nl>") if r.strip()]

    parsed_rows: List[List[str]] = []
    for row_str in row_strs:
        cells = _OTSL_CELL_SPLIT.split(row_str)
        cells = [c.strip() for c in cells if c.strip() or c == ""]
        if cells and cells[0] == "" and len(cells) > 1:
            cells = cells[1:]
        cells = [re.sub(r"\\+\(", "(", c).replace("\\)", ")") for c in cells]
        if cells:
            parsed_rows.append(cells)

    if not parsed_rows:
        return TableJSON(headers=[], rows=[])

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

    return TableJSON(headers=headers, rows=normalized)


def parse_markdown_table(text: str) -> Optional[TableJSON]:
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if not lines:
        return None

    header_idx = -1
    for i, line in enumerate(lines):
        if "|" in line and (i + 1 < len(lines) and "---" in lines[i + 1]):
            header_idx = i
            break
    if header_idx == -1:
        for i, line in enumerate(lines):
            if "|" in line and len(line.split("|")) > 2:
                header_idx = i
                break
    if header_idx == -1:
        return None

    def split_row(line: str) -> List[str]:
        parts = line.split("|")
        if parts and parts[0].strip() == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        return [p.strip() for p in parts]

    headers = split_row(lines[header_idx])
    if not headers:
        return None

    if header_idx + 1 < len(lines) and "---" in lines[header_idx + 1]:
        data_lines = lines[header_idx + 2 :]
    else:
        data_lines = lines[header_idx + 1 :]

    rows: List[List[str]] = []
    for line in data_lines:
        if "|" not in line:
            continue
        cells = split_row(line)
        if len(cells) < len(headers):
            cells = cells + [""] * (len(headers) - len(cells))
        elif len(cells) > len(headers):
            cells = cells[: len(headers)]
        rows.append(cells)

    return TableJSON(headers=headers, rows=rows)


def _try_parse_table_json(obj: Any) -> Optional[TableJSON]:
    if isinstance(obj, TableJSON):
        return obj
    if not isinstance(obj, dict):
        return None
    if "headers" in obj and "rows" in obj:
        try:
            return TableJSON(headers=[str(h) for h in obj["headers"]], rows=[[str(c) for c in r] for r in obj["rows"]])
        except Exception:
            return None
    if obj and all(isinstance(v, list) for v in obj.values()):
        headers = [str(k) for k in obj.keys()]
        max_len = max((len(v) for v in obj.values()), default=0)
        rows = []
        for i in range(max_len):
            rows.append([str(obj[h][i]) if i < len(obj[h]) else "" for h in headers])
        return TableJSON(headers=headers, rows=rows)
    return None


def normalize_table_content(raw: str) -> str:
    """Convert any table representation into canonical TableJSON JSON string."""
    if not raw or not str(raw).strip():
        return TableJSON().model_dump_json()

    text = str(raw).strip()

    try:
        parsed = json.loads(text)
        table = _try_parse_table_json(parsed)
        if table is not None:
            return table.model_dump_json()
        if isinstance(parsed, dict) and any(is_otsl(str(k)) or is_otsl(str(v)) for k, v in parsed.items()):
            parts = []
            for k, v in parsed.items():
                parts.append(str(k))
                if isinstance(v, str):
                    parts.append(v)
            return parse_otsl("".join(parts)).model_dump_json()
    except (json.JSONDecodeError, TypeError):
        pass

    if is_otsl(text):
        return parse_otsl(text).model_dump_json()

    md = parse_markdown_table(text)
    if md is not None and md.headers:
        return md.model_dump_json()

    return TableJSON(headers=["content"], rows=[[text]]).model_dump_json()


def merge_table_json(table1: str, table2: str) -> str:
    """Concatenate rows from two canonical (or normalizable) table JSON strings."""
    t1 = TableJSON.model_validate_json(normalize_table_content(table1))
    t2 = TableJSON.model_validate_json(normalize_table_content(table2))

    structure = None
    for raw in (table1, table2):
        try:
            obj = json.loads(raw) if isinstance(raw, str) else None
            if isinstance(obj, dict) and "_structure" in obj:
                structure = obj["_structure"]
                break
        except (json.JSONDecodeError, TypeError):
            pass

    if not t1.headers and t2.headers:
        out = t2.model_dump()
    elif not t2.headers:
        out = t1.model_dump()
    elif t1.headers == t2.headers:
        out = TableJSON(headers=t1.headers, rows=t1.rows + t2.rows).model_dump()
    elif t2.rows and [c.strip() for c in t2.rows[0]] == [c.strip() for c in t1.headers]:
        out = TableJSON(headers=t1.headers, rows=t1.rows + t2.rows[1:]).model_dump()
    else:
        width = len(t1.headers)
        extra = []
        for row in t2.rows:
            if len(row) < width:
                row = row + [""] * (width - len(row))
            else:
                row = row[:width]
            extra.append(row)
        out = TableJSON(headers=t1.headers, rows=t1.rows + extra).model_dump()

    if structure is not None:
        out["_structure"] = structure
    return json.dumps(out, ensure_ascii=False)
