from __future__ import annotations

import codecs
import csv
import io
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from aiogram import Bot

from domain.daily_attendance_status import PunchAt, evaluate_calendar_day_status
from infra.db import get_cursor
from repositories import employee_shift_config_repo
from repositories.clock_records_repo import ensure_clock_action_column
from repositories.temporary_leave_records_repo import TemporaryLeaveRecordRow, list_by_chat_and_range
from services.shift_import_service import ATTENDANCE_EXPORT_HEADERS_CN

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClockPunch:
    at: datetime
    action: str | None


@dataclass(frozen=True)
class AttendanceSummaryRow:
    chat_id: int
    group_name: str
    employee_id: str
    english_name: str
    shift_time_range: str
    first_clock_local: str
    last_clock_local: str
    leave_time_display: str
    status: str


def fallback_group_display_name_from_db(*, chat_id: int) -> str:
    """无 Telegram 群标题时：优先「组长英文名+组」，其次部门名，最后群 ID。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(lr.english_name, ''), COALESCE(o.department_name, '')
            FROM public.shifts s
            LEFT JOIN public.registrations r ON r.shift_id = s.id
            LEFT JOIN public.organizations o ON o.id = r.organization_id
            LEFT JOIN public.registrations lr ON lr.employee_id = o.leader_employee_id
            WHERE s.attendance_group_id = %s
            LIMIT 1
            """,
            (int(chat_id),),
        )
        row = cur.fetchone()
    if row:
        leader = str(row[0] or "").strip()
        dept = str(row[1] or "").strip()
        if leader:
            return f"{leader}组"
        if dept:
            return dept
    return f"群{chat_id}"


async def resolve_group_display_name(
    *,
    bot: Optional[Bot],
    chat_id: int,
    skip_telegram: bool = False,
) -> str:
    """优先 Telegram 群标题；失败则用数据库兜底。导出等批量场景可 skip_telegram 避免反复 get_chat 超时。"""
    if not skip_telegram and bot is not None:
        try:
            chat = await bot.get_chat(int(chat_id))
            title = (getattr(chat, "title", None) or "").strip()
            if title:
                return title
        except Exception as e:
            log.warning("resolve_group_display_name get_chat failed chat_id=%s: %s", chat_id, e)
    return fallback_group_display_name_from_db(chat_id=int(chat_id))


def ensure_tables() -> None:
    employee_shift_config_repo.ensure_table()
    ensure_clock_action_column()


def _parse_rest_days(raw: str) -> set[int]:
    out: set[int] = set()
    for p in (raw or "").replace("，", ",").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            d = int(p)
        except ValueError:
            continue
        if 1 <= d <= 31:
            out.add(d)
    return out


def _as_time(value: object) -> time:
    if isinstance(value, time):
        return value
    raw = str(value or "").strip()
    if not raw:
        return time(0, 0)
    parts = raw.split(":")
    if len(parts) >= 2:
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    return time.fromisoformat(raw)


def _bounds_utc(*, d: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    s = datetime.combine(d, time.min, tzinfo=tz)
    e = s + timedelta(days=1)
    return s.astimezone(timezone.utc), e.astimezone(timezone.utc)


def _fetch_group_workers(*, chat_id: int, year_month: str) -> List[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.employee_id, COALESCE(c.english_name, r.english_name, ''), c.shift_time_range,
                   c.shift_checkin_time, c.shift_checkout_time, c.monthly_rest_days,
                   s.timezone
            FROM public.registrations r
            JOIN public.shifts s ON s.id = r.shift_id
            JOIN public.employee_shift_config c
              ON c.employee_id = r.employee_id AND c.year_month = %s
            WHERE s.attendance_group_id = %s
            ORDER BY r.employee_id ASC
            """,
            (str(year_month), int(chat_id)),
        )
        rows = cur.fetchall() or []
    out: List[dict] = []
    for r in rows:
        out.append(
            {
                "employee_id": str(r[0]).strip(),
                "english_name": str(r[1] or ""),
                "shift_range": str(r[2] or ""),
                "cin": r[3],
                "cout": r[4],
                "rest_days": str(r[5] or ""),
                "tz": str(r[6] or "Asia/Shanghai"),
            }
        )
    return out


def _fetch_clock_map(
    *, chat_id: int, start_utc: datetime, end_utc: datetime
) -> Dict[str, List[ClockPunch]]:
    ensure_clock_action_column()
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT employee_id, clock_time, clock_action
            FROM public.clock_records
            WHERE chat_id = %s
              AND clock_time >= %s
              AND clock_time < %s
            ORDER BY employee_id ASC, clock_time ASC
            """,
            (int(chat_id), start_utc, end_utc),
        )
        rows = cur.fetchall() or []
    out: Dict[str, List[ClockPunch]] = defaultdict(list)
    for eid, t, action in rows:
        if isinstance(t, datetime):
            out[str(eid)].append(ClockPunch(at=t, action=str(action).strip() if action else None))
    return out


def _fmt_local_hms(dt: datetime, *, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%H:%M:%S")


def _format_duration_minutes(mins: int) -> str:
    if mins <= 0:
        return "0分钟"
    if mins < 60:
        return f"{mins}分钟"
    hours, rem = divmod(int(mins), 60)
    if rem:
        return f"{hours}小时{rem}分钟"
    return f"{hours}小时"


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _format_leave_time_display(*, records: List[TemporaryLeaveRecordRow], tz: ZoneInfo) -> str:
    """汇总当日离岗：已返岗显示时段+时长；仅有离岗未返岗则「未返岗」。"""
    if not records:
        return ""
    open_recs = [r for r in records if (r.status or "").upper() == "OPEN" or r.back_at is None]
    closed_recs = [r for r in records if r not in open_recs]
    if open_recs:
        return "未返岗"
    if not closed_recs:
        return ""
    total_mins = sum(int(r.duration_minutes or 0) for r in closed_recs)
    if len(closed_recs) == 1:
        rec = closed_recs[0]
        leave_at = _as_utc_aware(rec.leave_at)  # type: ignore[arg-type]
        back_at = _as_utc_aware(rec.back_at)  # type: ignore[arg-type]
        leave_s = _fmt_local_hms(leave_at, tz=tz)
        back_s = _fmt_local_hms(back_at, tz=tz)
        return f"{leave_s}-{back_s}({_format_duration_minutes(total_mins)})"
    return _format_duration_minutes(total_mins)


def _fetch_leave_map(
    *, chat_id: int, start_utc: datetime, end_utc: datetime
) -> Dict[str, List[TemporaryLeaveRecordRow]]:
    rows = list_by_chat_and_range(chat_id=int(chat_id), start_utc=start_utc, end_utc=end_utc)
    out: Dict[str, List[TemporaryLeaveRecordRow]] = defaultdict(list)
    for row in rows:
        out[str(row.employee_id).strip()].append(row)
    return out


def _to_punch_at(punches: List[ClockPunch]) -> List[PunchAt]:
    return [PunchAt(at=p.at, action=p.action) for p in punches]


def _status_for_row(
    *,
    d: date,
    row: dict,
    punches_today: List[ClockPunch],
    punches_yesterday: List[ClockPunch],
) -> tuple[str, str, str]:
    tz = ZoneInfo(row["tz"])
    cin = _as_time(row["cin"])
    cout = _as_time(row["cout"])
    rest = _parse_rest_days(row["rest_days"])
    status, checkin_utc, checkout_utc = evaluate_calendar_day_status(
        day=d,
        checkin=cin,
        checkout=cout,
        tz_name=row["tz"],
        rest_days=rest,
        punches_today=_to_punch_at(punches_today),
        punches_yesterday=_to_punch_at(punches_yesterday),
    )
    first = _fmt_local_hms(checkin_utc, tz=tz) if checkin_utc else ""
    last = _fmt_local_hms(checkout_utc, tz=tz) if checkout_utc else ""
    return status, first, last


def build_rows_for_group(
    *,
    chat_id: int,
    target_date: date,
    group_name: str = "",
) -> List[AttendanceSummaryRow]:
    year_month = target_date.strftime("%Y-%m")
    gname = (group_name or "").strip() or fallback_group_display_name_from_db(chat_id=int(chat_id))
    workers = _fetch_group_workers(chat_id=chat_id, year_month=year_month)
    if not workers:
        return []
    tz_name = workers[0]["tz"]
    day_start_utc, day_end_utc = _bounds_utc(d=target_date, tz_name=tz_name)
    prev_start_utc, _ = _bounds_utc(d=target_date - timedelta(days=1), tz_name=tz_name)
    clock_map = _fetch_clock_map(chat_id=chat_id, start_utc=prev_start_utc, end_utc=day_end_utc)
    leave_map = _fetch_leave_map(chat_id=chat_id, start_utc=day_start_utc, end_utc=day_end_utc)

    out: List[AttendanceSummaryRow] = []
    for w in workers:
        tz = ZoneInfo(w["tz"])
        all_punches = clock_map.get(w["employee_id"], [])
        punches_today = [p for p in all_punches if p.at.astimezone(tz).date() == target_date]
        prev_d = target_date - timedelta(days=1)
        punches_yesterday = [p for p in all_punches if p.at.astimezone(tz).date() == prev_d]
        status, first, last = _status_for_row(
            d=target_date,
            row=w,
            punches_today=punches_today,
            punches_yesterday=punches_yesterday,
        )
        tz = ZoneInfo(w["tz"])
        leave_display = _format_leave_time_display(
            records=leave_map.get(w["employee_id"], []),
            tz=tz,
        )
        if leave_map.get(w["employee_id"]):
            log.info(
                "[LEAVE_EXPORT] chat_id=%s employee_id=%s records=%s display=%r",
                chat_id,
                w["employee_id"],
                len(leave_map.get(w["employee_id"], [])),
                leave_display,
            )
        out.append(
            AttendanceSummaryRow(
                chat_id=int(chat_id),
                group_name=gname,
                employee_id=w["employee_id"],
                english_name=w["english_name"],
                shift_time_range=w["shift_range"],
                first_clock_local=first,
                last_clock_local=last,
                leave_time_display=leave_display,
                status=status,
            )
        )
    return out


def summarize_text(*, rows: Iterable[AttendanceSummaryRow], target_date: date) -> str:
    row_list = list(rows)
    by_status: Dict[str, List[str]] = defaultdict(list)
    for r in row_list:
        by_status[r.status].append(f"{r.english_name}({r.employee_id})")
    keys = ["缺卡", "迟到", "早退", "迟到+早退", "正常", "月休"]
    lines = [f"当日考勤统计 {target_date.isoformat()}"]
    for k in keys:
        vals = by_status.get(k, [])
        lines.append(f"{k}：{', '.join(vals) if vals else '无'}")
    not_back = [f"{r.english_name}({r.employee_id})" for r in row_list if r.leave_time_display == "未返岗"]
    lines.append(f"未返岗：{', '.join(not_back) if not_back else '无'}")
    if not (by_status.get("缺卡") or by_status.get("迟到") or by_status.get("早退") or by_status.get("迟到+早退")):
        lines.append("今日无异常，全部正常/休息。")
    return "\n".join(lines)


def encode_csv(*, rows: Iterable[AttendanceSummaryRow]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(ATTENDANCE_EXPORT_HEADERS_CN)
    for r in rows:
        writer.writerow(
            [
                r.group_name,
                r.employee_id,
                r.english_name,
                r.shift_time_range,
                r.first_clock_local,
                r.last_clock_local,
                r.leave_time_display,
                r.status,
            ]
        )
    return codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")


def list_attendance_group_ids() -> List[int]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT attendance_group_id
            FROM public.shifts
            WHERE attendance_group_id IS NOT NULL
            ORDER BY attendance_group_id ASC
            """
        )
        rows = cur.fetchall() or []
    return [int(r[0]) for r in rows if r and r[0] is not None]
