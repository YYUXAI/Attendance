from __future__ import annotations

import codecs
import csv
import io
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from domain import audit_rules
from infra.daily_report_config import DailyReportConfig, load_daily_report_config
from repositories import (
    clock_records_repo,
    event_logs_repo,
    registrations_repo,
    shifts_repo,
)
from repositories.shifts_repo import ShiftRow
from services.shift_import_service import DAILY_REPORT_HEADERS_CN

log = logging.getLogger(__name__)

REPORT_HEADERS = tuple(DAILY_REPORT_HEADERS_CN)


@dataclass(frozen=True)
class DailyReportRow:
    english_name: str
    employee_id: str
    shift_label: str
    checkin_local: str
    checkout_local: str


def _shift_label(shift: ShiftRow) -> str:
    def _fmt(t: object) -> str:
        if isinstance(t, time):
            return t.strftime("%H:%M")
        if isinstance(t, datetime):
            return t.strftime("%H:%M")
        return str(t)

    return f"{_fmt(shift.checkin_time)} - {_fmt(shift.checkout_time)}"


def _format_local_hm(dt_utc: datetime, tz_name: str) -> str:
    return dt_utc.astimezone(ZoneInfo(tz_name)).strftime("%H:%M:%S")


def _work_day_bounds_utc(*, work_date: date, tz_name: str) -> Tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(work_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _scheduled_checkin_local(*, work_date: date, shift: ShiftRow) -> datetime:
    tz = ZoneInfo(shift.timezone)
    cin_t = audit_rules.as_time(shift.checkin_time)
    return datetime.combine(work_date, cin_t, tzinfo=tz)


def _scheduled_checkout_local(*, work_date: date, shift: ShiftRow) -> datetime:
    tz = ZoneInfo(shift.timezone)
    cout_t = audit_rules.as_time(shift.checkout_time)
    cin_t = audit_rules.as_time(shift.checkin_time)
    overnight = bool(shift.is_overnight) or (cout_t <= cin_t)
    day = work_date + timedelta(days=1) if overnight else work_date
    return datetime.combine(day, cout_t, tzinfo=tz)


def _classify_single_punch(
    punch_utc: datetime,
    *,
    shift: ShiftRow,
    work_date: date,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    一天只打一次：按打卡时刻在「班次上/下班之间」的位置区分。
    - 偏上午/中午（早于上/下班中点）→ 只记上班时间
    - 偏晚上（晚于等于中点）→ 只记下班时间
    """
    tz = ZoneInfo(shift.timezone)
    punch_local = punch_utc.astimezone(tz)
    cin_local = _scheduled_checkin_local(work_date=work_date, shift=shift)
    cout_local = _scheduled_checkout_local(work_date=work_date, shift=shift)
    span = cout_local - cin_local
    if span.total_seconds() <= 0:
        span = timedelta(hours=1)
    midpoint = cin_local + span / 2
    if punch_local < midpoint:
        return punch_utc, None
    return None, punch_utc


def _pick_checkin_checkout(
    *,
    clock_times_utc: List[datetime],
    shift: ShiftRow,
    work_date: date,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    群打卡汇总表口径（展示用）：
    - 多次打卡：最早 → 上班，最晚 → 下班
    - 仅一次：相对班次上/下班中点，偏中午记上班、偏晚上记下班
    """
    if not clock_times_utc:
        return None, None
    times = sorted(clock_times_utc)
    if len(times) == 1 or times[0] == times[-1]:
        return _classify_single_punch(times[0], shift=shift, work_date=work_date)
    return times[0], times[-1]


def _rows_for_shift(*, shift: ShiftRow, report_instant_utc: datetime) -> List[DailyReportRow]:
    if shift.attendance_group_id is None:
        return []

    work_date = audit_rules.work_date_for_shift_day(
        shift_checkin_time=shift.checkin_time,
        instant_utc=report_instant_utc,
        timezone_name=shift.timezone,
        is_overnight=bool(shift.is_overnight),
    )
    day_start_utc, day_end_utc = _work_day_bounds_utc(work_date=work_date, tz_name=shift.timezone)

    regs = registrations_repo.list_by_shift_id(shift_id=int(shift.id))
    reg_by_eid = {str(r.employee_id): r for r in regs if r.employee_id}
    punched_ids = clock_records_repo.list_distinct_employee_ids_for_shift_in_range(
        shift_id=int(shift.id),
        start_at_utc=day_start_utc,
        end_at_utc=day_end_utc,
    )
    employee_ids = sorted(set(punched_ids))
    if not employee_ids:
        return []
    missing_regs = registrations_repo.list_by_employee_ids(employee_ids=employee_ids)
    for r in missing_regs:
        if r.employee_id and str(r.employee_id) not in reg_by_eid:
            reg_by_eid[str(r.employee_id)] = r

    records = clock_records_repo.list_clock_times_for_shift_employees_in_range(
        shift_id=int(shift.id),
        employee_ids=employee_ids,
        start_at_utc=day_start_utc,
        end_at_utc=day_end_utc,
    )
    times_by_eid: dict[str, List[datetime]] = defaultdict(list)
    for rec in records:
        if isinstance(rec.clock_time, datetime):
            times_by_eid[str(rec.employee_id)].append(rec.clock_time)

    label = _shift_label(shift)
    out: List[DailyReportRow] = []
    for eid in employee_ids:
        reg = reg_by_eid.get(eid)
        english = (reg.english_name if reg and reg.english_name else "") or ""
        clocks = sorted(times_by_eid.get(eid, []))
        checkin_utc, checkout_utc = _pick_checkin_checkout(
            clock_times_utc=clocks,
            shift=shift,
            work_date=work_date,
        )
        out.append(
            DailyReportRow(
                english_name=english,
                employee_id=eid,
                shift_label=label,
                checkin_local=_format_local_hm(checkin_utc, shift.timezone) if checkin_utc else "",
                checkout_local=_format_local_hm(checkout_utc, shift.timezone) if checkout_utc else "",
            )
        )
    return out


def build_report_rows(*, report_instant_utc: datetime) -> List[DailyReportRow]:
    rows: List[DailyReportRow] = []
    for shift in shifts_repo.list_all_shifts():
        rows.extend(_rows_for_shift(shift=shift, report_instant_utc=report_instant_utc))
    rows.sort(key=lambda r: (r.shift_label, r.employee_id))
    return rows


def encode_report_csv(*, rows: List[DailyReportRow]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(REPORT_HEADERS)
    for r in rows:
        writer.writerow(
            [r.employee_id, r.english_name, r.shift_label, r.checkin_local, r.checkout_local]
        )
    return codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")


def report_day_key(*, report_calendar_date: date) -> int:
    return int(report_calendar_date.strftime("%Y%m%d"))


def resolve_notify_tg_id(cfg: DailyReportConfig) -> Optional[int]:
    if cfg.notify_tg_id is not None:
        return int(cfg.notify_tg_id)
    reg = registrations_repo.get_by_tg_username(cfg.notify_username)
    if reg is None:
        log.error(
            "daily_report: cannot resolve notify user %r (set DAILY_ATTENDANCE_REPORT_NOTIFY_TG_ID)",
            cfg.notify_username,
        )
        return None
    return int(reg.tg_id)


def build_report_for_calendar_date(
    *,
    report_calendar_date: date,
    tz_name: str,
) -> Tuple[bytes, str, List[DailyReportRow]]:
    tz = ZoneInfo(tz_name)
    # 用当日 22:59:59 作为「当日考勤」归属时刻（23:00 任务触发前一日口径稳定）
    local_end = datetime.combine(
        report_calendar_date,
        time(22, 59, 59),
        tzinfo=tz,
    )
    instant_utc = local_end.astimezone(timezone.utc)
    rows = build_report_rows(report_instant_utc=instant_utc)
    part = report_calendar_date.isoformat()
    filename = f"attendance_daily_{part}.csv"
    return encode_report_csv(rows=rows), filename, rows
