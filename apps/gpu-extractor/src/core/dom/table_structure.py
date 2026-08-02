"""Table structure quality checks on TableJSON."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StructureIssue:
    rule_id: str
    severity: str
    message: str


@dataclass
class StructureReport:
    ok: bool
    issues: List[StructureIssue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> Dict[str, str]:
        return {
            "table_structure_ok": "true" if self.ok else "false",
            "table_structure_issues": json.dumps(
                [{"rule_id": i.rule_id, "severity": i.severity, "message": i.message} for i in self.issues]
            ),
            "table_row_count": str(self.stats.get("row_count", 0)),
            "table_col_count": str(self.stats.get("col_count", 0)),
            "table_ragged_rows": str(self.stats.get("ragged_rows", 0)),
            "table_empty_cell_ratio": f"{self.stats.get('empty_cell_ratio', 0.0):.3f}",
        }


def critique_table_json(raw: str) -> StructureReport:
    issues: List[StructureIssue] = []
    stats: Dict[str, Any] = {
        "row_count": 0,
        "col_count": 0,
        "ragged_rows": 0,
        "empty_cell_ratio": 0.0,
    }

    if not raw or not str(raw).strip():
        return StructureReport(
            ok=False,
            issues=[StructureIssue("table.empty", "hard", "Table content is empty after OCR normalization")],
            stats=stats,
        )

    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return StructureReport(
            ok=False,
            issues=[StructureIssue("table.not_json", "hard", "Table content is not valid JSON after normalization")],
            stats=stats,
        )

    headers = obj.get("headers") if isinstance(obj, dict) else None
    rows = obj.get("rows") if isinstance(obj, dict) else None
    if not isinstance(headers, list) or not isinstance(rows, list):
        return StructureReport(
            ok=False,
            issues=[StructureIssue("table.schema", "hard", "Table JSON missing headers/rows arrays")],
            stats=stats,
        )

    headers = [str(h).strip() for h in headers]
    width = len(headers)
    stats["col_count"] = width
    stats["row_count"] = len(rows)

    if width == 0:
        issues.append(StructureIssue("table.no_headers", "hard", "Table has zero header columns"))
    if not rows:
        issues.append(StructureIssue("table.no_rows", "soft", "Table has headers but zero data rows"))

    seen = set()
    blank_headers = 0
    for h in headers:
        key = h.lower()
        if not h:
            blank_headers += 1
        elif key in seen:
            issues.append(StructureIssue("table.duplicate_header", "soft", f"Duplicate header label '{h}'"))
        else:
            seen.add(key)
    if blank_headers:
        issues.append(StructureIssue("table.blank_headers", "soft", f"{blank_headers} blank header cell(s)"))

    empty = 0
    total_cells = 0
    ragged = 0
    for i, row in enumerate(rows):
        if not isinstance(row, list):
            issues.append(StructureIssue("table.row_not_list", "hard", f"Row {i} is not a list"))
            continue
        if width and len(row) != width:
            ragged += 1
        for cell in row:
            total_cells += 1
            if cell is None or str(cell).strip() == "":
                empty += 1

    stats["ragged_rows"] = ragged
    stats["empty_cell_ratio"] = (empty / total_cells) if total_cells else 0.0

    if ragged:
        severity = "hard" if ragged > max(1, len(rows) // 5) else "soft"
        issues.append(
            StructureIssue("table.ragged_rows", severity, f"{ragged} row(s) width ≠ header width {width}")
        )

    if stats["empty_cell_ratio"] > 0.6 and total_cells >= 8:
        issues.append(
            StructureIssue("table.sparse", "soft", f"High empty-cell ratio ({stats['empty_cell_ratio']:.0%})")
        )

    if headers == ["content"] and rows and len(rows) == 1:
        issues.append(
            StructureIssue(
                "table.fallback_blob",
                "soft",
                "Table fell back to single content blob — OCR structure likely failed",
            )
        )

    hard = any(i.severity == "hard" for i in issues)
    return StructureReport(ok=not hard, issues=issues, stats=stats)


def critique_table_json_safe(raw: Optional[str]) -> StructureReport:
    try:
        return critique_table_json(raw or "")
    except Exception as e:
        return StructureReport(
            ok=False,
            issues=[StructureIssue("table.critic_error", "hard", str(e))],
        )
