#!/usr/bin/env python3
"""One-off: check LINKWINE 21097 attendance status after deleting wrong check-in."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from zoneinfo import ZoneInfo

from domain.daily_attendance_status import PunchAt, evaluate_calendar_day_status
from infra.db import get_connection
from psycopg2.extras import RealDictCursor
from services.employee_shift_day_service import get_daily_shift, load_calendar_map

BJ = ZoneInfo("Asia/Shanghai")
EMPLOYEE_ID = "21097"
TZ = "Asia/Shanghai"


def _punches_for_day(all_rows, day: date) -> list[PunchAt]:
    start = datetime(day.year, day.month, day.day, tzinfo=BJ)
    end = start + timedelta(days=1)
    out: list[PunchAt] = []
    for r in all_rows:
        t = r["clock_time"].astimezone(BJ)
        if start <= t < end:
            out.append(PunchAt(at=r["clock_time"], action=r["clock_action"]))
    return out


def main() -> None:
    calendar_map = load_calendar_map(year_month="2026-07", employee_ids=[EMPLOYEE_ID])
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, clock_time, clock_action
            FROM public.clock_records
            WHERE employee_id = %s AND clock_time >= %s
            ORDER BY clock_time
            """,
            (EMPLOYEE_ID, datetime(2026, 7, 10, tzinfo=timezone.utc)),
        )
        rows = cur.fetchall()

    print("=== recent punches ===")
    for r in rows:
        bj = r["clock_time"].astimezone(BJ)
        print(f"{bj:%Y-%m-%d %H:%M:%S} {r['clock_action']} id={r['id']}")

    print("\n=== daily status 7/10-7/23 ===")
    abnormal: list[str] = []
    for d in range(10, 24):
        day = date(2026, 7, d)
        shift = get_daily_shift(
            employee_id=EMPLOYEE_ID,
            work_date=day,
            calendar_map=calendar_map,
        )
        if shift is None:
            print(f"{day}: no shift")
            continue
        if shift.is_rest:
            print(f"{day}: rest")
            continue
        prev_day = day - timedelta(days=1)
        prev_shift = get_daily_shift(
            employee_id=EMPLOYEE_ID,
            work_date=prev_day,
            calendar_map=calendar_map,
        )
        status, first, last = evaluate_calendar_day_status(
            day=day,
            checkin=shift.checkin,
            checkout=shift.checkout,
            tz_name=TZ,
            rest_days=set(),
            punches_today=_punches_for_day(rows, day),
            punches_yesterday=_punches_for_day(rows, prev_day),
            prev_checkin=prev_shift.checkin if prev_shift and not prev_shift.is_rest else None,
            prev_checkout=prev_shift.checkout if prev_shift and not prev_shift.is_rest else None,
            prev_was_rest=prev_shift.is_rest if prev_shift else None,
        )
        line = (
            f"{day} {shift.shift_code} {shift.checkin.strftime('%H:%M')}~"
            f"{shift.checkout.strftime('%H:%M')} -> {status}"
        )
        if first or last:
            line += f" ({first or '-'} / {last or '-'})"
        print(line)
        if status not in ("正常", "月休"):
            abnormal.append(line)

    print("\n=== summary ===")
    if abnormal:
        print("abnormal days:")
        for a in abnormal:
            print(" ", a)
    else:
        print("all checked days normal")


if __name__ == "__main__":
    main()
