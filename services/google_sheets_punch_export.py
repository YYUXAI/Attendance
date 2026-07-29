"""Google 表考勤回写：每日单元格展示上班卡/下班卡（月休保留）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from repositories.clock_records_repo import list_clock_records_by_employee_chat_in_range
from services.attendance_export_service import AttendanceExportOverview, EmployeeExportPivot

_PUNCH_SIGNIN = "上班卡"
_PUNCH_SIGNOUT = "下班卡"


def _day_bounds_utc(*, work_date: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(work_date, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _punch_flags_for_day(
    *,
    employee_id: str,
    chat_id: int,
    work_date: date,
    tz_name: str,
) -> tuple[bool, bool]:
    start_utc, end_utc = _day_bounds_utc(work_date=work_date, tz_name=tz_name)
    records = list_clock_records_by_employee_chat_in_range(
        employee_id=str(employee_id),
        chat_id=int(chat_id),
        start_at_utc=start_utc,
        end_at_utc=end_utc,
    )
    has_signin = any((r.clock_action or "").strip() == "签到" for r in records)
    has_signout = any((r.clock_action or "").strip() == "签退" for r in records)
    return has_signin, has_signout


def punch_status_for_day(
    *,
    employee_id: str,
    chat_id: int,
    work_date: date,
    tz_name: str,
    is_rest: bool,
) -> str:
    if is_rest:
        return "月休"
    has_signin, has_signout = _punch_flags_for_day(
        employee_id=employee_id,
        chat_id=chat_id,
        work_date=work_date,
        tz_name=tz_name,
    )
    parts: list[str] = []
    if has_signin:
        parts.append(_PUNCH_SIGNIN)
    if has_signout:
        parts.append(_PUNCH_SIGNOUT)
    return " ".join(parts)


def pivot_with_punch_status(
    *,
    pivot: list[EmployeeExportPivot],
    dates: list[date],
    chat_id: int,
    tz_name: str,
) -> list[EmployeeExportPivot]:
    out: list[EmployeeExportPivot] = []
    for p in pivot:
        daily: dict[date, str] = {}
        for d in dates:
            orig = (p.daily_status.get(d) or "").strip()
            daily[d] = punch_status_for_day(
                employee_id=p.employee_id,
                chat_id=int(chat_id),
                work_date=d,
                tz_name=tz_name,
                is_rest=orig == "月休",
            )
        out.append(replace(p, daily_status=daily))
    return out


def name_time_date_lines_for_day(
    *,
    english_name: str,
    employee_id: str,
    chat_id: int,
    work_date: date,
    tz_name: str,
    is_rest: bool,
) -> str:
    if is_rest:
        return "月休"
    start_utc, end_utc = _day_bounds_utc(work_date=work_date, tz_name=tz_name)
    records = list_clock_records_by_employee_chat_in_range(
        employee_id=str(employee_id),
        chat_id=int(chat_id),
        start_at_utc=start_utc,
        end_at_utc=end_utc,
    )
    if not records:
        return ""
    tz = ZoneInfo(tz_name)
    name = (english_name or "").strip() or str(employee_id)
    lines: list[str] = []
    for rec in sorted(records, key=lambda r: r.clock_time):
        local = rec.clock_time.astimezone(tz)
        lines.append(f"{name} {local.strftime('%H:%M:%S')} {local.strftime('%m-%d')}")
    return "\n".join(lines)


def pivot_with_name_time_date(
    *,
    pivot: list[EmployeeExportPivot],
    dates: list[date],
    chat_id: int,
    tz_name: str,
) -> list[EmployeeExportPivot]:
    out: list[EmployeeExportPivot] = []
    for p in pivot:
        daily: dict[date, str] = {}
        for d in dates:
            orig = (p.daily_status.get(d) or "").strip()
            daily[d] = name_time_date_lines_for_day(
                english_name=p.english_name,
                employee_id=p.employee_id,
                chat_id=int(chat_id),
                work_date=d,
                tz_name=tz_name,
                is_rest=orig == "月休",
            )
        out.append(replace(p, daily_status=daily))
    return out


def overview_for_punch_status(
    *,
    pivot: list[EmployeeExportPivot],
    dates: list[date],
) -> AttendanceExportOverview:
    signin = signout = rest = 0
    for p in pivot:
        for d in dates:
            st = (p.daily_status.get(d) or "").strip()
            if not st:
                continue
            if st == "月休":
                rest += 1
            else:
                if _PUNCH_SIGNIN in st:
                    signin += 1
                if _PUNCH_SIGNOUT in st:
                    signout += 1
    return AttendanceExportOverview(
        expected_count=len(pivot),
        actual_count=signin,
        monthly_rest=rest,
        absent=0,
        late=0,
        early=0,
        missed_punch=0,
        leave=signout,
    )
