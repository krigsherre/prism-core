#!/usr/bin/env python3
"""
Offline financial extraction accuracy eval.

Usage (from apps/schema-aligner):
  poetry run python evals/run_eval.py
  poetry run python evals/run_eval.py --fixtures evals/golden
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.financial_numerics import nearly_equal, parse_financial_number 
from core.verification import CriticAgent
from core.critic_types import Severity 


@dataclass
class CellScore:
    column: str
    expected: Any
    predicted: Any
    match: bool
    reason: str = ""


@dataclass
class DocResult:
    document_id: str
    target_table: str
    cell_scores: List[CellScore] = field(default_factory=list)
    critic_ok: bool = True
    critic_error: str = ""
    schema_ok: bool = True

    @property
    def matched(self) -> int:
        return sum(1 for c in self.cell_scores if c.match)

    @property
    def total(self) -> int:
        return len(self.cell_scores)

    @property
    def cell_f1_proxy(self) -> float:
        return self.matched / self.total if self.total else 1.0


def _cell_match(expected: Any, predicted: Any, tol: float = 0.01) -> tuple[bool, str]:
    if expected is None:
        return True, "no gold"
    exp_num = parse_financial_number(expected)
    pred_num = parse_financial_number(predicted)
    if exp_num is not None or pred_num is not None:
        if nearly_equal(exp_num, pred_num, abs_tol=tol, rel_tol=0.002):
            return True, "numeric"
        return False, f"numeric mismatch {predicted!r} vs {expected!r}"
    exp_s = str(expected).strip().lower()
    pred_s = "" if predicted is None else str(predicted).strip().lower()
    if exp_s == pred_s:
        return True, "exact"
    return False, f"string mismatch {predicted!r} vs {expected!r}"


def evaluate_fixture(path: Path, critic: CriticAgent) -> DocResult:
    payload = json.loads(path.read_text())
    doc_id = payload.get("document_id", path.stem)
    target_table = payload["target_table"]
    extracted_rows: List[Dict[str, Any]] = payload.get("extracted_rows") or []
    if not extracted_rows and payload.get("extracted_row"):
        extracted_rows = [payload["extracted_row"]]

    result = DocResult(document_id=doc_id, target_table=target_table)

    predicted_table = payload.get("predicted_table", target_table)
    result.schema_ok = predicted_table == target_table

    detailed = critic.verify_document_detailed(target_table, extracted_rows)
    hard_fails = [r for r in detailed if not r.ok and r.severity == Severity.HARD]
    soft_fails = [r for r in detailed if not r.ok and r.severity == Severity.SOFT]
    ok = len(hard_fails) == 0
    err = hard_fails[0].as_error_string() if hard_fails else (
        soft_fails[0].as_error_string() if soft_fails else ""
    )

    expect_fail = bool(payload.get("_expect_critic_fail"))
    expect_soft = bool(payload.get("_expect_soft_fail"))
    if expect_fail:
        result.critic_ok = len(hard_fails) > 0
        result.critic_error = "" if result.critic_ok else "expected HARD critic failure but passed"
    elif expect_soft:
        result.critic_ok = len(soft_fails) > 0 and len(hard_fails) == 0
        result.critic_error = "" if result.critic_ok else "expected SOFT critic failure"
    else:
        result.critic_ok = ok
        result.critic_error = err

    if expect_fail or expect_soft:
        return result

    gold_cells = payload.get("cells") or []
    for cell in gold_cells:
        row_index = int(cell.get("row_index", 0))
        column = cell["column"]
        expected = cell.get("value")
        tol = float(cell.get("tolerance", 0.01))
        predicted = None
        if 0 <= row_index < len(extracted_rows):
            predicted = extracted_rows[row_index].get(column)
        match, reason = _cell_match(expected, predicted, tol=tol)
        result.cell_scores.append(
            CellScore(column=column, expected=expected, predicted=predicted, match=match, reason=reason)
        )

    for rel in payload.get("relations") or []:
        if rel.get("type") != "sum_equals":
            continue
        result.cell_scores.append(
            CellScore(
                column=rel.get("left", "relation"),
                expected="identity",
                predicted="ok" if result.critic_ok else result.critic_error,
                match=result.critic_ok,
                reason="relation",
            )
        )

    return result


def summarize(results: List[DocResult]) -> Dict[str, Any]:
    total_cells = sum(r.total for r in results)
    matched = sum(r.matched for r in results)
    critic_pass = sum(1 for r in results if r.critic_ok)
    schema_pass = sum(1 for r in results if r.schema_ok)
    n = len(results) or 1
    return {
        "documents": len(results),
        "cell_accuracy": (matched / total_cells) if total_cells else 1.0,
        "cells_matched": matched,
        "cells_total": total_cells,
        "critic_pass_rate": critic_pass / n,
        "schema_accuracy": schema_pass / n,
        "failed_docs": [
            {
                "document_id": r.document_id,
                "target_table": r.target_table,
                "cell_accuracy": r.cell_f1_proxy,
                "critic_ok": r.critic_ok,
                "critic_error": r.critic_error,
                "misses": [
                    {"column": c.column, "expected": c.expected, "predicted": c.predicted, "reason": c.reason}
                    for c in r.cell_scores
                    if not c.match
                ],
            }
            for r in results
            if (r.total and r.matched < r.total) or not r.critic_ok or not r.schema_ok
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prism financial extraction eval")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).parent / "golden",
        help="Directory of golden JSON fixtures",
    )
    parser.add_argument("--min-cell-accuracy", type=float, default=0.95)
    parser.add_argument("--min-critic-pass", type=float, default=1.0)
    args = parser.parse_args()

    fixtures = sorted(p for p in args.fixtures.rglob("*.json") if p.is_file())
    if not fixtures:
        print(f"No fixtures in {args.fixtures}", file=sys.stderr)
        return 2

    critic = CriticAgent()
    results = [evaluate_fixture(p, critic) for p in fixtures]
    summary = summarize(results)
    print(json.dumps(summary, indent=2))

    if summary["cell_accuracy"] < args.min_cell_accuracy:
        print(
            f"FAIL cell_accuracy {summary['cell_accuracy']:.3f} < {args.min_cell_accuracy}",
            file=sys.stderr,
        )
        return 1
    if summary["critic_pass_rate"] < args.min_critic_pass:
        print(
            f"FAIL critic_pass_rate {summary['critic_pass_rate']:.3f} < {args.min_critic_pass}",
            file=sys.stderr,
        )
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
