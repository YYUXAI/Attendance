#!/usr/bin/env python3
"""清洗 registrations 中误粘贴「请输入」「示例」等的英文名/工号。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from domain.registration.rules import (
    normalize_employee_id_for_template,
    normalize_english_name_for_template,
)
from infra.db import get_cursor
from repositories import registrations_repo


def _find_dirty() -> list[tuple[int, str, str | None, str, str]]:
    out: list[tuple[int, str, str | None, str, str]] = []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, english_name, tg_id
            FROM public.registrations
            ORDER BY CAST(employee_id AS BIGINT)
            """
        )
        rows = cur.fetchall() or []
    for rid, eid, en, tg_id in rows:
        clean_eid = normalize_employee_id_for_template(str(eid))
        clean_en = normalize_english_name_for_template(en)
        if not clean_eid:
            continue
        if str(eid) != clean_eid or (en or "").strip() != clean_en:
            out.append((int(rid), str(eid), en, clean_eid, clean_en))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗脏注册数据")
    parser.add_argument("--apply", action="store_true", help="写入数据库（默认仅预览）")
    args = parser.parse_args()

    dirty = _find_dirty()
    print(f"dirty records: {len(dirty)}")
    if not dirty:
        print("无需清洗")
        return 0

    for rid, old_eid, old_en, new_eid, new_en in dirty:
        conflict = registrations_repo.get_by_employee_id(new_eid)
        conflict_note = ""
        if conflict and str(conflict.employee_id) != old_eid:
            conflict_note = f" CONFLICT tg={conflict.tg_id}"
        print(
            f"  id={rid} tg=? | eid {old_eid!r} -> {new_eid!r} | "
            f"name {old_en!r} -> {new_en!r}{conflict_note}"
        )

    if not args.apply:
        print("\n预览模式；加 --apply 执行更新")
        return 0

    updated = skipped = 0
    with get_cursor() as cur:
        for rid, old_eid, old_en, new_eid, new_en in dirty:
            if old_eid != new_eid:
                cur.execute(
                    "SELECT 1 FROM public.registrations WHERE employee_id = %s AND id <> %s",
                    (new_eid, rid),
                )
                if cur.fetchone():
                    print(f"SKIP id={rid}: 目标工号 {new_eid} 已存在")
                    skipped += 1
                    continue
            cur.execute(
                """
                UPDATE public.registrations
                SET employee_id = %s,
                    english_name = %s
                WHERE id = %s
                """,
                (new_eid, new_en, rid),
            )
            updated += 1
    print(f"done: updated={updated} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
