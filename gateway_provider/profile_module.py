from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from psycopg2.extensions import cursor as Cursor

from domain.daily_attendance_status import is_midnight_noon_shift
from services.employee_shift_day_service import (
    DailyShift,
    daily_shift_from_calendar_row,
)
from services.group_attendance_summary_service import (
    ClockPunch,
    compute_month_stats_from_punches,
)


def profile_text_for_tg_id(
    cursor: Cursor,
    *,
    tg_id: int,
    now_utc: datetime | None = None,
) -> str:
    now = _utc(now_utc or datetime.now(timezone.utc))
    cursor.execute(
        """
        SELECT employee_id, english_name
        FROM public.registrations
        WHERE tg_id = %s
        """,
        (int(tg_id),),
    )
    registration = cursor.fetchone()
    if registration is None:
        return "你还未完成注册，请先注册后再查看我的信息。"

    employee_id = str(registration[0])
    english_name = str(registration[1] or "").strip() or "（未填英文名）"
    tz_name = "Asia/Shanghai"
    tz = ZoneInfo(tz_name)
    as_of_local = now.astimezone(tz).date()
    month_start, month_end = _month_range(as_of_local)
    year_month = month_start.strftime("%Y-%m")
    cursor.execute(
        """
        SELECT shift_checkin_time, shift_checkout_time,
               shift_time_range, monthly_rest_days
        FROM public.employee_shift_config
        WHERE employee_id = %s AND year_month = %s
        """,
        (employee_id, year_month),
    )
    shift = cursor.fetchone()
    if shift is None:
        return (
            f"姓名：{html.escape(english_name)}\n"
            f"工号：{html.escape(employee_id)}\n"
            "班次：未配置"
        )

    checkin = _as_time(shift[0])
    checkout = _as_time(shift[1])
    configured_range = str(shift[2] or "").strip()
    rest_days = str(shift[3] or "")
    calendar_map = _calendar_map(
        cursor,
        employee_id=employee_id,
        year_month=year_month,
    )
    shift_display = _today_shift_display(
        employee_id=employee_id,
        as_of_local=as_of_local,
        configured_range=configured_range,
        checkin=checkin,
        checkout=checkout,
        calendar_map=calendar_map,
    )
    chat_id = _latest_attendance_chat(cursor, employee_id=employee_id)
    punches = _month_punches(
        cursor,
        employee_id=employee_id,
        chat_id=chat_id,
        month_start=month_start,
        as_of_local=as_of_local,
        tz=tz,
    )
    stats = compute_month_stats_from_punches(
        employee_id=employee_id,
        month_start=month_start,
        month_end=month_end,
        as_of_local=as_of_local,
        checkin=checkin,
        checkout=checkout,
        rest_days_raw=rest_days,
        tz_name=tz_name,
        calendar_map=calendar_map,
        punches=punches,
    )
    return (
        f"姓名：{html.escape(english_name)}\n"
        f"工号：{html.escape(employee_id)}\n"
        f"班次：{html.escape(shift_display)}\n"
        "-----------------------\n"
        f"本月已出勤天数：{stats.attendance_days}天\n"
        f"本月缺卡次数：{stats.missing_count}次\n"
        f"本月迟到次数：{stats.late_count}次\n"
        f"本月早退次数：{stats.early_count}次"
    )


def _month_range(value: date) -> tuple[date, date]:
    first = date(value.year, value.month, 1)
    next_first = (
        date(value.year + 1, 1, 1)
        if value.month == 12
        else date(value.year, value.month + 1, 1)
    )
    return first, next_first - timedelta(days=1)


def _calendar_map(
    cursor: Cursor,
    *,
    employee_id: str,
    year_month: str,
) -> dict[tuple[str, date], DailyShift]:
    cursor.execute(
        """
        SELECT work_date, shift_code, cell_kind
        FROM public.employee_shift_calendar
        WHERE employee_id = %s AND year_month = %s
        ORDER BY work_date
        """,
        (employee_id, year_month),
    )
    result: dict[tuple[str, date], DailyShift] = {}
    for work_date, shift_code, cell_kind in cursor.fetchall() or []:
        daily_shift = daily_shift_from_calendar_row(
            shift_code=str(shift_code or ""),
            cell_kind=str(cell_kind or ""),
        )
        if daily_shift is not None:
            result[(employee_id, work_date)] = daily_shift
    return result


def _latest_attendance_chat(cursor: Cursor, *, employee_id: str) -> int | None:
    cursor.execute(
        """
        SELECT chat_id
        FROM public.clock_records
        WHERE employee_id = %s
        ORDER BY clock_time DESC
        LIMIT 1
        """,
        (employee_id,),
    )
    row = cursor.fetchone()
    return int(row[0]) if row is not None and row[0] is not None else None


def _month_punches(
    cursor: Cursor,
    *,
    employee_id: str,
    chat_id: int | None,
    month_start: date,
    as_of_local: date,
    tz: ZoneInfo,
) -> list[ClockPunch]:
    if chat_id is None:
        return []
    start = datetime.combine(month_start - timedelta(days=1), time.min, tzinfo=tz)
    end = datetime.combine(as_of_local + timedelta(days=2), time.min, tzinfo=tz)
    cursor.execute(
        """
        SELECT clock_time, clock_action
        FROM public.clock_records
        WHERE employee_id = %s
          AND chat_id = %s
          AND clock_time >= %s
          AND clock_time < %s
        ORDER BY clock_time
        """,
        (employee_id, chat_id, start.astimezone(timezone.utc), end.astimezone(timezone.utc)),
    )
    return [
        ClockPunch(at=_utc(clock_time), action=str(action) if action else None)
        for clock_time, action in cursor.fetchall() or []
        if isinstance(clock_time, datetime)
    ]


def _today_shift_display(
    *,
    employee_id: str,
    as_of_local: date,
    configured_range: str,
    checkin: time,
    checkout: time,
    calendar_map: dict[tuple[str, date], DailyShift],
) -> str:
    daily = calendar_map.get((employee_id, as_of_local))
    configured = configured_range or f"{checkin} - {checkout}（Asia/Shanghai）"
    if daily is None or daily.is_rest or is_midnight_noon_shift(
        checkin=checkin,
        checkout=checkout,
    ):
        return configured.replace("~", " - ")
    return daily.shift_time_range.replace("~", " - ")


def _as_time(value: object) -> time:
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
