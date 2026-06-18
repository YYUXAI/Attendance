"""按 6 月班表生成 5 月假数据：班表配置 + 打卡记录。"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from infra.db import get_cursor
from repositories import employee_shift_config_repo
from repositories.clock_records_repo import insert_clock_record

TZ = ZoneInfo("Asia/Shanghai")
SOURCE_YM = "2026-06"
TARGET_YM = "2026-05"
DEFAULT_CHAT_ID = -1003200046237
FAKE_FILE_ID = "fake_may_seed"


def _parse_rest_days(raw: str) -> set[int]:
    out: set[int] = set()
    for p in (raw or "").replace("，", ",").split(","):
        p = p.strip()
        if p.isdigit():
            d = int(p)
            if 1 <= d <= 31:
                out.add(d)
    return out


def _copy_shift_config(*, source_ym: str, target_ym: str) -> int:
    employee_shift_config_repo.ensure_table()
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT employee_id, english_name, shift_time_range,
                   shift_checkin_time, shift_checkout_time, monthly_rest_days
            FROM public.employee_shift_config
            WHERE year_month = %s
            ORDER BY employee_id
            """,
            (source_ym,),
        )
        rows = cur.fetchall() or []
    for r in rows:
        employee_shift_config_repo.upsert_config(
            year_month=target_ym,
            employee_id=str(r[0]),
            english_name=str(r[1]),
            shift_time_range=str(r[2]),
            shift_checkin_time=r[3],
            shift_checkout_time=r[4],
            monthly_rest_days=str(r[5] or ""),
        )
    return len(rows)


def _load_employee_meta() -> dict[str, dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.employee_id, r.tg_id, COALESCE(c.english_name, r.english_name),
                   c.shift_checkin_time, c.shift_checkout_time, c.monthly_rest_days,
                   (
                     SELECT cr.chat_id
                     FROM public.clock_records cr
                     WHERE cr.employee_id = r.employee_id
                     ORDER BY cr.clock_time DESC
                     LIMIT 1
                   )
            FROM public.registrations r
            JOIN public.employee_shift_config c
              ON c.employee_id = r.employee_id AND c.year_month = %s
            ORDER BY r.employee_id
            """,
            (TARGET_YM,),
        )
        rows = cur.fetchall() or []
    out: dict[str, dict] = {}
    for r in rows:
        eid = str(r[0]).strip()
        out[eid] = {
            "tg_id": int(r[1]),
            "english_name": str(r[2] or ""),
            "cin": r[3],
            "cout": r[4],
            "rest_days": _parse_rest_days(str(r[5] or "")),
            "chat_id": int(r[6]) if r[6] is not None else DEFAULT_CHAT_ID,
        }
    return out


def _local_dt(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=TZ)


def _day_pattern(*, eid: str, day: int) -> str:
    """normal | late | early | miss_in | miss_out | absent"""
    key = (hash(eid) + day * 17) % 100
    if key < 62:
        return "normal"
    if key < 72:
        return "late"
    if key < 80:
        return "early"
    if key < 88:
        return "miss_out"
    if key < 94:
        return "miss_in"
    return "absent"


def _clear_may_clocks() -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            DELETE FROM public.clock_records
            WHERE clock_time >= %s AND clock_time < %s
            """,
            (
                datetime(2026, 5, 1, tzinfo=TZ),
                datetime(2026, 6, 1, tzinfo=TZ),
            ),
        )
        return int(cur.rowcount or 0)


def seed_may_fake_data(*, clear_existing: bool = True) -> None:
    copied = _copy_shift_config(source_ym=SOURCE_YM, target_ym=TARGET_YM)
    if copied == 0:
        raise RuntimeError(f"未找到 {SOURCE_YM} 班表，请先维护 6 月班次")

    deleted = 0
    if clear_existing:
        deleted = _clear_may_clocks()

    employees = _load_employee_meta()
    if not employees:
        raise RuntimeError("无已注册且已导入 5 月班表的员工")

    may_days = [date(2026, 5, d) for d in range(1, 32)]
    inserted = 0
    for eid, meta in employees.items():
        cin: time = meta["cin"]
        cout: time = meta["cout"]
        rest_days: set[int] = meta["rest_days"]
        chat_id = meta["chat_id"]
        tg_id = meta["tg_id"]

        for d in may_days:
            if d.day in rest_days:
                continue
            pattern = _day_pattern(eid=eid, day=d.day)
            if pattern == "absent":
                continue

            in_t = cin
            out_t = cout
            if pattern == "late":
                in_t = (datetime.combine(d, cin) + timedelta(minutes=18)).time()
            elif pattern == "early":
                out_t = (datetime.combine(d, cout) - timedelta(minutes=25)).time()

            if pattern != "miss_in":
                insert_clock_record(
                    chat_id=chat_id,
                    file_id=FAKE_FILE_ID,
                    tg_id=tg_id,
                    employee_id=eid,
                    shift_id=None,
                    clock_time_utc=_local_dt(d, in_t),
                    clock_action="签到",
                )
                inserted += 1
            if pattern != "miss_out":
                out_day = d
                if cout <= cin:
                    out_day = d + timedelta(days=1)
                insert_clock_record(
                    chat_id=chat_id,
                    file_id=FAKE_FILE_ID,
                    tg_id=tg_id,
                    employee_id=eid,
                    shift_id=None,
                    clock_time_utc=_local_dt(out_day, out_t),
                    clock_action="签退",
                )
                inserted += 1

    print(f"班表: 已从 {SOURCE_YM} 复制 {copied} 人到 {TARGET_YM}")
    if clear_existing:
        print(f"打卡: 已清除 5 月旧记录 {deleted} 条")
    print(f"打卡: 新插入 {inserted} 条（{len(employees)} 人 × 5 月工作日）")


def main() -> None:
    p = argparse.ArgumentParser(description="按 6 月班表生成 5 月假数据")
    p.add_argument(
        "--keep-existing",
        action="store_true",
        help="不清除已有 5 月打卡，仅追加（默认会先清空 5 月打卡）",
    )
    args = p.parse_args()
    seed_may_fake_data(clear_existing=not args.keep_existing)


if __name__ == "__main__":
    main()
