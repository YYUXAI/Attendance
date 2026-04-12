from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple, Optional, Tuple
from zoneinfo import ZoneInfo


_DOLLAR_HM = re.compile(r"^(\d{2})\$(\d{2})$")


class ShiftTimeBounds(NamedTuple):
    window_start_local: datetime
    window_end_local: datetime
    effective_end_cap_local: datetime


def normalize_db_time(value: object) -> time:
    """将 shifts.checkin_time / checkout_time 等统一为 time（兼容 timedelta）。"""
    if isinstance(value, time):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, timedelta):
        total = int(value.total_seconds()) % 86400
        h, r = divmod(total, 3600)
        m, s = divmod(r, 60)
        return time(h, m, s)
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    raise TypeError(f"unsupported time value: {type(value)!r}")


def parse_hour_minute_dollar(text: str) -> Optional[Tuple[int, int]]:
    raw = (text or "").strip()
    m = _DOLLAR_HM.match(raw)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    if h > 23 or mm > 59:
        return None
    return h, mm


def compute_logic_work_date(*, now_utc: datetime, timezone_name: str, is_overnight: bool, checkin_time: object) -> date:
    """
    docs00：非跨夜 work_date = 班次时区本地自然日（不因早于上班时间回拨）；
    跨夜：若本地时间 < 上班时间 → 前一天，否则当天。
    """
    tz = ZoneInfo(timezone_name)
    local = now_utc.astimezone(tz)
    today = local.date()
    if not is_overnight:
        return today
    ci = normalize_db_time(checkin_time)
    if local.time() < ci:
        return today - timedelta(days=1)
    return today


def build_shift_time_bounds_for_work_date(
    *,
    work_date: date,
    timezone_name: str,
    is_overnight: bool,
    checkin_time: object,
    checkout_time: object,
) -> ShiftTimeBounds:
    tz = ZoneInfo(timezone_name)
    ci = normalize_db_time(checkin_time)
    co = normalize_db_time(checkout_time)
    window_start = datetime.combine(work_date, ci, tzinfo=tz)
    if not is_overnight:
        window_end = datetime.combine(work_date, co, tzinfo=tz)
    else:
        window_end = datetime.combine(work_date + timedelta(days=1), co, tzinfo=tz)
    eod = datetime.combine(work_date, time(23, 59, 59, 999999), tzinfo=tz)
    effective_end_cap = window_end if window_end <= eod else eod
    return ShiftTimeBounds(
        window_start_local=window_start,
        window_end_local=window_end,
        effective_end_cap_local=effective_end_cap,
    )


def local_window_to_utc_start_end(
    *,
    work_date: date,
    timezone_name: str,
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
) -> Tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    s = datetime.combine(work_date, time(start_h, start_m), tzinfo=tz)
    e = datetime.combine(work_date, time(end_h, end_m), tzinfo=tz)
    return s.astimezone(timezone.utc), e.astimezone(timezone.utc)


def validate_temporary_leave_same_day_window(
    *,
    work_date: date,
    timezone_name: str,
    is_overnight: bool,
    checkin_time: object,
    checkout_time: object,
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
) -> Optional[str]:
    """
    返回 None 表示通过；否则为对用户展示的错误文案（直接 reply，不入队）。
    """
    if end_h < start_h or (end_h == start_h and end_m <= start_m):
        return "结束时间必须晚于开始时间，请重新输入离岗结束时间。"

    bounds = build_shift_time_bounds_for_work_date(
        work_date=work_date,
        timezone_name=timezone_name,
        is_overnight=is_overnight,
        checkin_time=checkin_time,
        checkout_time=checkout_time,
    )
    tz = ZoneInfo(timezone_name)
    user_start = datetime.combine(work_date, time(start_h, start_m), tzinfo=tz)
    user_end = datetime.combine(work_date, time(end_h, end_m), tzinfo=tz)

    if user_start < bounds.window_start_local or user_end > bounds.effective_end_cap_local:
        return "离岗时段必须落在当班时间范围内，请重新输入。"

    if user_start >= user_end:
        return "结束时间必须晚于开始时间，请重新输入离岗结束时间。"

    return None
