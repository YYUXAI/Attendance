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
from repositories import employee_shift_config_repo, registrations_repo, shifts_repo
from repositories.clock_records_repo import ensure_clock_action_column
from repositories.temporary_leave_records_repo import TemporaryLeaveRecordRow, list_by_chat_and_range
from services.shift_import_service import ATTENDANCE_EXPORT_HEADERS_CN

log = logging.getLogger(__name__)

# 打卡截图按北京时间入库（见 handlers/checkin.py）；班表时段按考勤群班次时区解读。
_CHECKIN_STORE_TZ = "Asia/Shanghai"
_DEFAULT_SHIFT_TZ = "Asia/Bangkok"


def _timezone_for_attendance_group(*, chat_id: int) -> str:
    rows = shifts_repo.list_by_attendance_group_id(attendance_group_id=int(chat_id))
    for s in rows:
        tz = (s.timezone or "").strip()
        if tz:
            return tz
    return _DEFAULT_SHIFT_TZ


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
    work_date: Optional[date] = None


@dataclass(frozen=True)
class ShiftStartNoticePerson:
    english_name: str
    tg_username: str | None


@dataclass(frozen=True)
class ShiftStartNoticeBuckets:
    """与导出 CSV / build_rows_for_group 同一套日状态口径。"""

    should_count: int
    arrived: List[ShiftStartNoticePerson]
    on_rest: List[ShiftStartNoticePerson]
    late: List[ShiftStartNoticePerson]
    absent: List[ShiftStartNoticePerson]


@dataclass(frozen=True)
class EmployeeMonthAttendanceStats:
    """与导出/23:00 汇总同一套 evaluate_calendar_day_status 口径。"""

    attendance_days: int
    missing_count: int
    late_count: int
    early_count: int


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
    """在册 + 当月班表；须曾在本群打过卡（不依赖 registrations.shift_id）。"""
    shift_tz = _timezone_for_attendance_group(chat_id=int(chat_id))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.employee_id, COALESCE(c.english_name, r.english_name, ''), r.tg_username,
                   c.shift_time_range, c.shift_checkin_time, c.shift_checkout_time, c.monthly_rest_days
            FROM public.registrations r
            JOIN public.employee_shift_config c
              ON c.employee_id = r.employee_id AND c.year_month = %s
            WHERE EXISTS (
                SELECT 1
                FROM public.clock_records cr
                WHERE cr.employee_id = r.employee_id
                  AND cr.chat_id = %s
            )
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
                "tg_username": (str(r[2]).strip() if r[2] else None) or None,
                "shift_range": str(r[3] or ""),
                "cin": r[4],
                "cout": r[5],
                "rest_days": str(r[6] or ""),
                "tz": shift_tz,
            }
        )
    return out


def _format_shift_range_label(*, shift_range: str, cin: object, cout: object) -> str:
    rng = (shift_range or "").strip()
    if rng:
        return rng.replace("~", " - ").replace("—", " - ").replace("–", " - ")
    if isinstance(cin, time) and isinstance(cout, time):
        return f"{cin.strftime('%H:%M')} - {cout.strftime('%H:%M')}"
    return ""


def distinct_shift_labels_for_group(*, chat_id: int, year_month: str) -> str:
    """从当月班表汇总本群所有不重复班次时段（用于开班群公告展示）。"""
    workers = _fetch_group_workers(chat_id=int(chat_id), year_month=str(year_month))
    if not workers:
        return ""
    items: list[tuple[time, str]] = []
    seen: set[str] = set()
    for w in workers:
        label = _format_shift_range_label(
            shift_range=str(w.get("shift_range") or ""),
            cin=w.get("cin"),
            cout=w.get("cout"),
        )
        if not label or label in seen:
            continue
        seen.add(label)
        cin = w.get("cin")
        sort_key = cin if isinstance(cin, time) else time(0, 0)
        items.append((sort_key, label))
    items.sort(key=lambda x: x[0])
    return " / ".join(lbl for _, lbl in items)


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


def _punches_for_employee_in_range(
    *,
    employee_id: str,
    shift_id: int | None,
    chat_id: int | None,
    start_utc: datetime,
    end_utc: datetime,
) -> List[ClockPunch]:
    ensure_clock_action_column()
    if chat_id is not None:
        from repositories.clock_records_repo import list_clock_records_by_employee_chat_in_range

        rows = list_clock_records_by_employee_chat_in_range(
            employee_id=employee_id,
            chat_id=int(chat_id),
            start_at_utc=start_utc,
            end_at_utc=end_utc,
        )
    elif shift_id is not None:
        from repositories.clock_records_repo import list_clock_records_in_range

        rows = list_clock_records_in_range(
            employee_id=employee_id,
            shift_id=int(shift_id),
            start_at_utc=start_utc,
            end_at_utc=end_utc,
        )
    else:
        return []
    if not rows and chat_id is not None:
        return list(_fetch_clock_map(chat_id=int(chat_id), start_utc=start_utc, end_utc=end_utc).get(employee_id, []))
    out: List[ClockPunch] = []
    for r in rows:
        if isinstance(r.clock_time, datetime):
            out.append(
                ClockPunch(
                    at=r.clock_time,
                    action=str(r.clock_action).strip() if r.clock_action else None,
                )
            )
    return out


def compute_month_stats_for_employee(
    *,
    employee_id: str,
    shift_id: int | None = None,
    chat_id: int | None,
    month_start: date,
    month_end: date,
    as_of_local: date,
    checkin: time,
    checkout: time,
    rest_days_raw: str,
    tz_name: str,
) -> EmployeeMonthAttendanceStats:
    """
    按自然日汇总本月考勤（与导出 CSV、群 23:00 统计同规则）：
    - 迟到：实际上班时间 > 班次上班时间
    - 早退：实际下班时间 < 班次下班时间
    - 缺卡：当日应打未打齐（含跨夜班规则）；月休日不计
    只统计 as_of_local 及之前的日期，不统计当月未来日期。
    """
    tz = ZoneInfo(tz_name)
    last_day = min(month_end, as_of_local)
    if last_day < month_start:
        return EmployeeMonthAttendanceStats(0, 0, 0, 0)

    range_start = month_start - timedelta(days=1)
    range_end = last_day + timedelta(days=1)
    start_utc, _ = _bounds_utc(d=range_start, tz_name=tz_name)
    _, end_utc = _bounds_utc(d=range_end, tz_name=tz_name)
    all_punches = _punches_for_employee_in_range(
        employee_id=employee_id,
        shift_id=shift_id,
        chat_id=chat_id,
        start_utc=start_utc,
        end_utc=end_utc,
    )
    row = {
        "tz": tz_name,
        "cin": checkin,
        "cout": checkout,
        "rest_days": rest_days_raw,
    }

    attendance_days = 0
    missing_count = 0
    late_count = 0
    early_count = 0
    d = month_start
    while d <= last_day:
        punches_today = [p for p in all_punches if _local_date(p.at, tz) == d]
        prev_d = d - timedelta(days=1)
        punches_yesterday = [p for p in all_punches if _local_date(p.at, tz) == prev_d]
        status, _, _ = _status_for_row(
            d=d,
            row=row,
            punches_today=punches_today,
            punches_yesterday=punches_yesterday,
        )
        if status == "月休":
            d += timedelta(days=1)
            continue
        if status != "缺卡":
            attendance_days += 1
        if status == "缺卡":
            missing_count += 1
        elif status == "迟到":
            late_count += 1
        elif status == "早退":
            early_count += 1
        elif status == "迟到+早退":
            late_count += 1
            early_count += 1
        d += timedelta(days=1)

    return EmployeeMonthAttendanceStats(
        attendance_days=attendance_days,
        missing_count=missing_count,
        late_count=late_count,
        early_count=early_count,
    )


def _local_date(dt: datetime, tz: ZoneInfo) -> date:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(tz).date()
    return dt.astimezone(tz).date()


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


def compute_shift_start_notice_buckets(
    *,
    chat_id: int,
    target_date: date,
    shift_id: int | None = None,
) -> ShiftStartNoticeBuckets:
    """
    开班群公告人数统计：与 build_rows_for_group / 当日导出同一规则。
    - 月休 → 报备休假名单（employee_shift_config.monthly_rest_days）
    - 缺卡 → 未打卡名单
    - 迟到 / 迟到+早退 → 迟到名单（且计入已到岗）
    - 正常 / 早退 → 已到岗
    - 今日应到岗 = 非月休人数

    shift_id：若指定则只统计该班次在册且已导入当月班次的员工（与群发范围一致）。
    """
    ensure_tables()
    year_month = target_date.strftime("%Y-%m")
    workers = _fetch_group_workers(chat_id=int(chat_id), year_month=year_month)
    if shift_id is not None:
        allowed = {
            str(r.employee_id).strip()
            for r in registrations_repo.list_by_shift_id(shift_id=int(shift_id))
            if r.employee_id
        }
        # registrations.shift_id 未配置时不过滤，避免统计人数恒为 0
        if allowed:
            workers = [w for w in workers if w["employee_id"] in allowed]
    if not workers:
        return ShiftStartNoticeBuckets(0, [], [], [], [])

    tz_name = workers[0]["tz"]
    day_start_utc, day_end_utc = _bounds_utc(d=target_date, tz_name=tz_name)
    prev_start_utc, _ = _bounds_utc(d=target_date - timedelta(days=1), tz_name=tz_name)
    clock_map = _fetch_clock_map(chat_id=int(chat_id), start_utc=prev_start_utc, end_utc=day_end_utc)

    arrived: List[ShiftStartNoticePerson] = []
    on_rest: List[ShiftStartNoticePerson] = []
    late: List[ShiftStartNoticePerson] = []
    absent: List[ShiftStartNoticePerson] = []

    for w in workers:
        tz = ZoneInfo(w["tz"])
        all_punches = clock_map.get(w["employee_id"], [])
        punches_today = [p for p in all_punches if p.at.astimezone(tz).date() == target_date]
        prev_d = target_date - timedelta(days=1)
        punches_yesterday = [p for p in all_punches if p.at.astimezone(tz).date() == prev_d]
        status, _, _ = _status_for_row(
            d=target_date,
            row=w,
            punches_today=punches_today,
            punches_yesterday=punches_yesterday,
        )
        person = ShiftStartNoticePerson(
            english_name=str(w["english_name"] or ""),
            tg_username=w.get("tg_username"),
        )
        if status == "月休":
            on_rest.append(person)
        elif status == "缺卡":
            absent.append(person)
        elif status in ("迟到", "迟到+早退"):
            late.append(person)
            arrived.append(person)
        else:
            arrived.append(person)

    should_count = len(workers) - len(on_rest)
    return ShiftStartNoticeBuckets(
        should_count=should_count,
        arrived=arrived,
        on_rest=on_rest,
        late=late,
        absent=absent,
    )


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


def dedupe_export_rows_by_employee(
    *, rows: Iterable[AttendanceSummaryRow]
) -> List[AttendanceSummaryRow]:
    """全局导出：同一工号只保留一行（多人曾在多个群打卡时会重复）。"""
    by_eid: Dict[str, List[AttendanceSummaryRow]] = defaultdict(list)
    for r in rows:
        by_eid[str(r.employee_id).strip()].append(r)

    def _score(row: AttendanceSummaryRow) -> tuple[int, int, int]:
        has_clock = 1 if (row.first_clock_local or row.last_clock_local) else 0
        status_rank = {
            "正常": 5,
            "迟到": 4,
            "早退": 4,
            "迟到+早退": 3,
            "月休": 2,
            "缺卡": 0,
        }.get(row.status, 1)
        generic_group = 1 if row.group_name in ("当月班表", "") else 0
        return (has_clock, status_rank, generic_group)

    out: List[AttendanceSummaryRow] = []
    for eid in sorted(by_eid.keys()):
        candidates = by_eid[eid]
        out.append(max(candidates, key=_score))
    return out


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
    """班次配置的考勤群 + 实际出现过打卡记录的群（避免只在「未登记群」打卡的人漏导出）。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT gid
            FROM (
                SELECT attendance_group_id AS gid
                FROM public.shifts
                WHERE attendance_group_id IS NOT NULL
                UNION
                SELECT chat_id AS gid
                FROM public.clock_records
                WHERE chat_id IS NOT NULL
            ) t
            ORDER BY gid ASC
            """
        )
        rows = cur.fetchall() or []
    return [int(r[0]) for r in rows if r and r[0] is not None]


def _fetch_monthly_roster_workers(*, year_month: str) -> List[dict]:
    """当月班表全员（不依赖 shift_id、不要求已在某群打卡）。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.employee_id, COALESCE(c.english_name, r.english_name, ''), r.tg_username,
                   c.shift_time_range, c.shift_checkin_time, c.shift_checkout_time, c.monthly_rest_days
            FROM public.registrations r
            JOIN public.employee_shift_config c
              ON c.employee_id = r.employee_id AND c.year_month = %s
            ORDER BY r.employee_id ASC
            """,
            (str(year_month),),
        )
        rows = cur.fetchall() or []
    out: List[dict] = []
    for r in rows:
        out.append(
            {
                "employee_id": str(r[0]).strip(),
                "english_name": str(r[1] or ""),
                "tg_username": (str(r[2]).strip() if r[2] else None) or None,
                "shift_range": str(r[3] or ""),
                "cin": r[4],
                "cout": r[5],
                "rest_days": str(r[6] or ""),
                "tz": _DEFAULT_SHIFT_TZ,
            }
        )
    return out


def build_rows_for_monthly_roster_remainder(
    *,
    target_date: date,
    exclude_employee_ids: set[str],
) -> List[AttendanceSummaryRow]:
    """班表中有、前面各群导出尚未包含的员工（按最近打卡群统计当日状态）。"""
    from repositories.clock_records_repo import get_latest_chat_id_for_employee

    year_month = target_date.strftime("%Y-%m")
    workers = _fetch_monthly_roster_workers(year_month=year_month)
    out: List[AttendanceSummaryRow] = []
    for w in workers:
        eid = w["employee_id"]
        if eid in exclude_employee_ids:
            continue
        chat_id = get_latest_chat_id_for_employee(employee_id=eid)
        if chat_id is None:
            tz = ZoneInfo(w["tz"])
            status, first, last = _status_for_row(
                d=target_date,
                row=w,
                punches_today=[],
                punches_yesterday=[],
            )
            out.append(
                AttendanceSummaryRow(
                    chat_id=0,
                    group_name="当月班表",
                    employee_id=eid,
                    english_name=w["english_name"],
                    shift_time_range=w["shift_range"],
                    first_clock_local=first,
                    last_clock_local=last,
                    leave_time_display="",
                    status=status,
                )
            )
            continue
        gname = fallback_group_display_name_from_db(chat_id=int(chat_id))
        tz_name = w["tz"]
        day_start_utc, day_end_utc = _bounds_utc(d=target_date, tz_name=tz_name)
        prev_start_utc, _ = _bounds_utc(d=target_date - timedelta(days=1), tz_name=tz_name)
        clock_map = _fetch_clock_map(chat_id=int(chat_id), start_utc=prev_start_utc, end_utc=day_end_utc)
        leave_map = _fetch_leave_map(chat_id=chat_id, start_utc=day_start_utc, end_utc=day_end_utc)
        tz = ZoneInfo(tz_name)
        all_punches = clock_map.get(eid, [])
        punches_today = [p for p in all_punches if p.at.astimezone(tz).date() == target_date]
        prev_d = target_date - timedelta(days=1)
        punches_yesterday = [p for p in all_punches if p.at.astimezone(tz).date() == prev_d]
        status, first, last = _status_for_row(
            d=target_date,
            row=w,
            punches_today=punches_today,
            punches_yesterday=punches_yesterday,
        )
        leave_display = _format_leave_time_display(
            records=leave_map.get(eid, []),
            tz=tz,
        )
        out.append(
            AttendanceSummaryRow(
                chat_id=int(chat_id),
                group_name=gname,
                employee_id=eid,
                english_name=w["english_name"],
                shift_time_range=w["shift_range"],
                first_clock_local=first,
                last_clock_local=last,
                leave_time_display=leave_display,
                status=status,
            )
        )
    return out
