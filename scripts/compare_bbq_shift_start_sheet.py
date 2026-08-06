"""对比 Y-UX-KQBBQ 开班总汇名单与 Google 班表。"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from infra.db import get_cursor
from infra.google_sheets_config import load_google_sheets_config
from repositories import registrations_repo
from services import group_attendance_summary_service as g
from services.google_sheets_shift_sync_service import fetch_shift_matrix_sheet, parse_shift_matrix

CHAT_ID = int(os.getenv("COMPARE_BBQ_CHAT_ID", "0"))
SHIFT_ID = 1
REST_MARKERS = ("▲", "△", "休", "月休")


def _is_rest_cell(cell: str) -> bool:
    c = (cell or "").strip()
    if not c:
        return False
    if c in REST_MARKERS:
        return True
    return any(m in c for m in REST_MARKERS)


def main() -> None:
    today = date.today()
    cfg = load_google_sheets_config()
    _, rows = fetch_shift_matrix_sheet(
        spreadsheet_id=cfg.spreadsheet_id,
        credentials_json=cfg.credentials_json,
        year_month=cfg.year_month,
        source="main",
        fallback_gid=cfg.sheet_gid,
    )
    _, parsed = parse_shift_matrix(rows, year_month=cfg.year_month)
    sheet_ids = {p.employee_id for p in parsed}
    sheet_names = {p.employee_id: p.english_name for p in parsed}

    sheet_work_today: set[str] = set()
    sheet_rest_today: set[str] = set()
    for p in parsed:
        cell = p.daily.get(today.day, "")
        if _is_rest_cell(cell):
            sheet_rest_today.add(p.employee_id)
        elif (cell.strip().upper() if cell else p.primary_code):
            sheet_work_today.add(p.employee_id)

    buckets = g.compute_shift_start_notice_buckets(
        chat_id=CHAT_ID, target_date=today, shift_id=SHIFT_ID
    )
    reg_ids = {
        str(r.employee_id).strip()
        for r in registrations_repo.list_by_shift_id(shift_id=SHIFT_ID)
        if r.employee_id
    }
    workers = g._fetch_group_workers(chat_id=CHAT_ID, year_month=today.strftime("%Y-%m"))
    worker_ids = {w["employee_id"] for w in workers}
    notice_scope = (worker_ids & reg_ids) if reg_ids else worker_ids

    print("=== CONFIG ===")
    print(f"sheet_id={cfg.spreadsheet_id} gid={cfg.sheet_gid}")
    print(f"date={today.isoformat()}")
    print(f"sheet_total={len(sheet_ids)} sheet_work_today={len(sheet_work_today)} sheet_rest={len(sheet_rest_today)}")

    print("\n=== SHIFT START (3003) ===")
    print(f"reg_shift1={len(reg_ids)} clocked_in_bbq={len(worker_ids)} scope={len(notice_scope)}")
    print(
        f"should={buckets.should_count} arrived={len(buckets.arrived)} "
        f"rest={len(buckets.on_rest)} absent={len(buckets.absent)} late={len(buckets.late)}"
    )

    only_sheet = sheet_ids - notice_scope
    only_notice = notice_scope - sheet_ids
    sheet_work_not_in_scope = sheet_work_today - notice_scope
    notice_in_sheet_rest = notice_scope & sheet_rest_today

    print("\n=== DIFF sheet vs notice scope ===")
    print(f"in_sheet_not_in_notice={len(only_sheet)}")
    for eid in sorted(only_sheet):
        tag = "rest" if eid in sheet_rest_today else "work"
        print(f"  {eid} {sheet_names.get(eid, '?')} [{tag}]")

    print(f"\nin_notice_not_in_sheet={len(only_notice)}")
    for eid in sorted(only_notice):
        w = next((x for x in workers if x["employee_id"] == eid), None)
        print(f"  {eid} {w['english_name'] if w else '?'}")

    print(f"\nnotice_scope_but_sheet_rest={len(notice_in_sheet_rest)}")
    for eid in sorted(notice_in_sheet_rest):
        print(f"  {eid} {sheet_names.get(eid, '?')}")

    print(f"\nsheet_work_today_not_in_notice={len(sheet_work_not_in_scope)}")
    for eid in sorted(sheet_work_not_in_scope):
        print(
            f"  {eid} {sheet_names.get(eid, '?')} "
            f"reg={eid in reg_ids} clock={eid in worker_ids}"
        )

    print("\n=== NOTICE NAMES ===")
    print("rest:", ", ".join(p.english_name for p in buckets.on_rest) or "-")
    print("absent:", ", ".join(p.english_name for p in buckets.absent) or "-")
    print("late:", ", ".join(p.english_name for p in buckets.late) or "-")
    print("arrived:", ", ".join(p.english_name for p in buckets.arrived) or "-")

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, status, created_at, LEFT(payload::text, 200)
            FROM public.notifications
            WHERE template_id = 3003 AND shift_id = %s AND work_date = %s
            ORDER BY id DESC LIMIT 3
            """,
            (SHIFT_ID, today),
        )
        notifs = cur.fetchall()
    print("\n=== 3003 notifications today ===")
    if not notifs:
        print("none")
    else:
        for n in notifs:
            print(n)


if __name__ == "__main__":
    main()
