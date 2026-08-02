#!/usr/bin/env python3
"""Export HITL extraction_corrections into schema-aligner evals/golden/hitl."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ALIGNER_SRC = ROOT.parent / "schema-aligner" / "src"
if ALIGNER_SRC.exists():
    sys.path.insert(0, str(ALIGNER_SRC))

from utils.corrections import (  # noqa: E402
    correction_to_golden,
    list_unpromoted_corrections,
    mark_promoted,
)

DEFAULT_OUT = ROOT.parent / "schema-aligner" / "evals" / "golden" / "hitl"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", (value or "correction").strip())
    return cleaned.strip("_").lower()[:80] or "correction"


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    for key in ("before_data", "after_data", "field_patches", "synonym_mappings", "reflexion_meta"):
        if key in row:
            row[key] = _parse_jsonish(row.get(key))
    return row


def _validate_golden(fixture: Dict[str, Any]) -> tuple[bool, str]:
    try:
        from core.verification import CriticAgent
        from core.critic_types import Severity
    except Exception as e:
        return True, f"critic unavailable ({e})"

    table = fixture.get("target_table") or ""
    rows = fixture.get("extracted_rows") or []
    if not rows and fixture.get("extracted_row"):
        rows = [fixture["extracted_row"]]
    if not rows:
        return False, "empty extracted row"

    detailed = CriticAgent().verify_document_detailed(table, rows)
    hard = [r for r in detailed if not r.ok and r.severity == Severity.HARD]
    if hard:
        fixture["_expect_critic_fail"] = True
        fixture["_export_note"] = hard[0].as_error_string()
        return True, f"negative golden ({hard[0].rule_id})"
    return True, "critic pass"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(_normalize_row(json.loads(line)))
    return rows


async def fetch_db(limit: int) -> List[Dict[str, Any]]:
    import asyncpg

    database_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("database_url")
        or "postgresql://postgres:postgres@localhost:5432/prism"
    ).replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(database_url)
    try:
        return [_normalize_row(r) for r in await list_unpromoted_corrections(conn, limit=limit)]
    finally:
        await conn.close()


async def mark_db(ids: List[str]) -> None:
    import asyncpg

    database_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("database_url")
        or "postgresql://postgres:postgres@localhost:5432/prism"
    ).replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(database_url)
    try:
        await mark_promoted(conn, ids)
    finally:
        await conn.close()


async def run(
    out_dir: Path,
    limit: int,
    dry_run: bool,
    validate: bool,
    from_jsonl: Optional[Path],
    skip_mark: bool,
) -> int:
    if from_jsonl:
        rows = load_jsonl(from_jsonl)[:limit]
    else:
        try:
            rows = await fetch_db(limit)
        except Exception as e:
            print(f"DB fetch failed: {e}", file=sys.stderr)
            return 1

    if not rows:
        print("No unpromoted corrections to export.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    written_ids: List[str] = []
    skipped = 0

    for row in rows:
        fixture = dict(correction_to_golden(row))
        fixture["_source"] = "hitl_correction"
        fixture["_correction_id"] = row.get("id")
        fixture["_tenant_id"] = row.get("tenant_id")

        note = ""
        if validate:
            ok, note = _validate_golden(fixture)
            if not ok:
                print(f"skip {row.get('id')}: {note}")
                skipped += 1
                continue

        fname = (
            f"hitl_{_slug(str(row.get('target_table') or 'table'))}"
            f"_{_slug(str(row.get('id') or 'x')[:12])}.json"
        )
        path = out_dir / fname
        body = json.dumps(fixture, indent=2, default=str) + "\n"
        if dry_run:
            print(f"[dry-run] would write {path} ({note or 'ok'})")
        else:
            path.write_text(body, encoding="utf-8")
            print(f"Wrote {path} ({note or 'ok'})")
        if row.get("id"):
            written_ids.append(str(row["id"]))

    if dry_run:
        print(f"[dry-run] would mark {len(written_ids)} promoted (skipped {skipped})")
    elif written_ids and not skip_mark and not from_jsonl:
        await mark_db(written_ids)
        print(f"Marked {len(written_ids)} correction(s) promoted_to_eval=true")
    elif from_jsonl:
        print(f"Exported {len(written_ids)} from JSONL")
    else:
        print(f"Exported {len(written_ids)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Export HITL corrections to eval goldens")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate", action="store_true", default=True)
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--from-jsonl", type=Path)
    parser.add_argument("--skip-mark", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                args.out,
                args.limit,
                args.dry_run,
                not args.no_validate,
                args.from_jsonl,
                args.skip_mark,
            )
        )
    )


if __name__ == "__main__":
    main()
