"""从 MGZ Google 班表批量预注册：工号 + 「名字」列。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=True, encoding="utf-8")

from infra.google_sheets_alt_config import load_google_sheets_alt_config
from repositories import registrations_repo
from services.google_sheets_client import fetch_sheet_values
from services.google_sheets_shift_sync_service import parse_shift_matrix


def _resolve_chat_id() -> int | None:
    alt = load_google_sheets_alt_config()
    if alt and alt.attendance_chat_id is not None:
        return int(alt.attendance_chat_id)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Google MGZ 班表批量预注册")
    parser.add_argument(
        "--spreadsheet-id",
        default="1PvfjRqbrSxeuS_3qSxg3nqAr6ngosZyZrC5fqeO-k78",
    )
    parser.add_argument("--sheet-gid", type=int, default=922677905)
    parser.add_argument("--year-month", default="2026-07")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    alt = load_google_sheets_alt_config()
    creds = (
        (alt.credentials_json if alt else "")
        or "secrets/google_service_account.json"
    )
    chat_id = _resolve_chat_id()

    title, rows = fetch_sheet_values(
        spreadsheet_id=str(args.spreadsheet_id).strip(),
        credentials_json=creds,
        sheet_gid=int(args.sheet_gid),
    )
    _, employees = parse_shift_matrix(rows, year_month=str(args.year_month).strip())
    print(f"sheet={title!r} employees={len(employees)} chat_id={chat_id} dry_run={args.dry_run}")

    stats = {"inserted": 0, "updated": 0, "skipped_bound": 0}
    for emp in employees:
        name = (emp.english_name or "").strip() or (emp.chinese_name or "").strip() or emp.employee_id
        if args.dry_run:
            existing = registrations_repo.get_by_employee_id(emp.employee_id)
            if existing is None:
                action = "insert"
            elif existing.tg_id is not None:
                action = "skip_bound"
            else:
                action = "update"
            print(f"  [{action}] {emp.employee_id} {name}")
            stats[{"insert": "inserted", "update": "updated", "skip_bound": "skipped_bound"}[action]] += 1
            continue

        action = registrations_repo.upsert_registration_stub(
            employee_id=emp.employee_id,
            english_name=name,
            registered_chat_id=chat_id,
        )
        stats[action] = stats.get(action, 0) + 1
        print(f"  [{action}] {emp.employee_id} {name}")

    print(
        f"done: inserted={stats['inserted']} updated={stats['updated']} "
        f"skipped_bound={stats['skipped_bound']}"
    )


if __name__ == "__main__":
    main()
