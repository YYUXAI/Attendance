"""对比所有启用 BBQ capability 的群与 Google 班表。"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from infra.google_sheets_config import load_google_sheets_config
from repositories import attendance_runtime_config_repo, registrations_repo
from services import group_attendance_summary_service as g
from services.google_sheets_shift_sync_service import fetch_shift_matrix_sheet, parse_shift_matrix

SHIFT_ID = 1
REST_MARKERS = ("▲", "△", "休", "月休")


def _is_rest_cell(cell: str) -> bool:
    c = (cell or "").strip()
    if not c:
        return False
    if c in REST_MARKERS:
        return True
    return any(m in c for m in REST_MARKERS)


def _compare_group(*, chat_id: int) -> None:
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
        chat_id=chat_id, target_date=today, shift_id=SHIFT_ID
    )
    reg_ids = {
        str(r.employee_id).strip()
        for r in registrations_repo.list_by_shift_id(shift_id=SHIFT_ID)
        if r.employee_id
    }
    workers = g._fetch_group_workers(chat_id=chat_id, year_month=today.strftime("%Y-%m"))
    worker_ids = {w["employee_id"] for w in workers}
    notice_scope = (worker_ids & reg_ids) if reg_ids else worker_ids

    print("=== CONFIG ===")
    print(f"chat_id={chat_id} sheet_binding=configured")
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


def main() -> None:
    chat_ids = attendance_runtime_config_repo.active_chat_ids_with_capability(
        capability="bbq-google-sheets"
    )
    if not chat_ids:
        print("没有 active bbq-google-sheets 群")
        return
    for chat_id in chat_ids:
        _compare_group(chat_id=chat_id)

if __name__ == "__main__":
    main()
