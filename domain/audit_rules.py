from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional, Sequence

from zoneinfo import ZoneInfo


AUDIT_STAGE_CHECKIN = "CHECKIN"
AUDIT_STAGE_CHECKOUT = "CHECKOUT"

AUDIT_RESULT_NORMAL = "NORMAL"
AUDIT_RESULT_LATE = "LATE"
AUDIT_RESULT_EARLY_LEAVE = "EARLY_LEAVE"
AUDIT_RESULT_ABSENT = "ABSENT"
AUDIT_RESULT_ON_LEAVE = "ON_LEAVE"
AUDIT_RESULT_TEMPORARY_LEAVE = "TEMPORARY_LEAVE"
AUDIT_RESULT_EXEMPT = "EXEMPT"
AUDIT_RESULT_NONE = "NONE"


@dataclass(frozen=True)
class AuditDecision:
    result: str
    valid_clock_time_utc: Optional[datetime]
    is_terminal: bool


def _to_timedelta(v: object) -> timedelta:
    """
    支持 PostgreSQL interval（常见映射为 datetime.timedelta），或 int/float（视为分钟）。
    """
    if isinstance(v, timedelta):
        return v
    if isinstance(v, (int, float)):
        return timedelta(minutes=float(v))
    raise TypeError(f"Unsupported interval type: {type(v)!r}")


def _as_time(v: object) -> time:
    if isinstance(v, time):
        return v
    if isinstance(v, datetime):
        return v.timetz().replace(tzinfo=None)
    raise TypeError(f"Unsupported time type: {type(v)!r}")


def as_time(v: object) -> time:
    """公开版本，供 service 侧进行日期组合（不暴露私有函数名）。"""
    return _as_time(v)


def work_date_for_shift_day(
    *,
    shift_checkin_time: object,
    instant_utc: datetime,
    timezone_name: str,
    is_overnight: bool,
) -> date:
    """
    docs00 口径：逻辑工作日 = 上班开始那天。
    给定任意时刻 instant_utc，返回其在班次时区下归属到的“上班日”。

    修正口径：
    - 非跨夜班（is_overnight=False）：work_date 必须等于班次时区下的本地自然日，
      不因“当前时间 < checkin_time”回拨到昨天。
    - 跨夜班（is_overnight=True）：才允许在“当前时间 < checkin_time”时归属到前一工作日。
    """
    tz = ZoneInfo(timezone_name)
    local_dt = instant_utc.astimezone(tz)
    checkin_t = _as_time(shift_checkin_time)
    local_d = local_dt.date()
    if not bool(is_overnight):
        return local_d
    # 跨夜班：若当前时间在上班开始之前，归属到前一工作日
    if local_dt.timetz().replace(tzinfo=None) < checkin_t:
        return local_d - timedelta(days=1)
    return local_d


@dataclass(frozen=True)
class Window:
    start_utc: datetime
    end_utc: datetime  # 半开区间 [start_utc, end_utc)


def compute_checkin_window_utc(
    *,
    target_work_date: date,
    shift_checkin_time: object,
    timezone_name: str,
    attendance_flex_interval: object,
) -> Window:
    """
    上班有效打卡窗口：以 shifts.checkin_time 为中心，使用 attendance_flex_interval 做对称窗口。
    """
    flex = _to_timedelta(attendance_flex_interval)
    checkin_t = _as_time(shift_checkin_time)
    tz = ZoneInfo(timezone_name)
    center_local = datetime.combine(target_work_date, checkin_t, tzinfo=tz)
    start_local = center_local - flex
    end_local = center_local + flex
    return Window(start_utc=start_local.astimezone(timezone.utc), end_utc=end_local.astimezone(timezone.utc))


def compute_checkout_window_utc(
    *,
    target_work_date: date,
    shift_checkin_time: object,
    shift_checkout_time: object,
    timezone_name: str,
    is_overnight: bool,
    attendance_flex_interval: object,
) -> Window:
    """
    下班有效打卡窗口：以 shifts.checkout_time 为中心，使用 attendance_flex_interval 做对称窗口。
    日期归属仍是 target_work_date（上班日）；若跨夜，下班中心时刻落在次日。
    """
    flex = _to_timedelta(attendance_flex_interval)
    checkout_t = _as_time(shift_checkout_time)
    tz = ZoneInfo(timezone_name)
    day = target_work_date + timedelta(days=1) if bool(is_overnight) else target_work_date
    center_local = datetime.combine(day, checkout_t, tzinfo=tz)
    start_local = center_local - flex
    end_local = center_local + flex
    return Window(start_utc=start_local.astimezone(timezone.utc), end_utc=end_local.astimezone(timezone.utc))


def _scheduled_checkin_instant_utc(*, target_work_date: date, shift_checkin_time: object, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    t = _as_time(shift_checkin_time)
    return datetime.combine(target_work_date, t, tzinfo=tz).astimezone(timezone.utc)


def _scheduled_checkout_instant_utc(
    *,
    target_work_date: date,
    shift_checkout_time: object,
    timezone_name: str,
    is_overnight: bool,
) -> datetime:
    tz = ZoneInfo(timezone_name)
    t = _as_time(shift_checkout_time)
    d = target_work_date + timedelta(days=1) if bool(is_overnight) else target_work_date
    return datetime.combine(d, t, tzinfo=tz).astimezone(timezone.utc)


def decide_checkin(
    *,
    now_utc: datetime,
    target_work_date: date,
    shift_checkin_time: object,
    timezone_name: str,
    attendance_flex_interval: object,
    max_late_early_tolerance: object,
    # 事实优先级输入（由 service 从生效表/免审配置加载；domain 不访问 DB）
    is_on_leave: bool,
    is_temporary_leave_covering: bool,
    is_exempt: bool,
    # 该员工在“有效窗口内”的打卡时间序列（UTC，升序）
    window_clock_times_utc: Sequence[datetime],
) -> AuditDecision:
    """
    CHECKIN 判定：
    - 只取有效窗口内最早打卡
    - 优先级：ON_LEAVE > TEMPORARY_LEAVE > EXEMPT > 打卡判定
    """
    if is_on_leave:
        return AuditDecision(result=AUDIT_RESULT_ON_LEAVE, valid_clock_time_utc=None, is_terminal=True)
    if is_temporary_leave_covering:
        return AuditDecision(result=AUDIT_RESULT_TEMPORARY_LEAVE, valid_clock_time_utc=None, is_terminal=True)
    if is_exempt:
        return AuditDecision(result=AUDIT_RESULT_EXEMPT, valid_clock_time_utc=None, is_terminal=True)

    tol = _to_timedelta(max_late_early_tolerance)
    scheduled_utc = _scheduled_checkin_instant_utc(
        target_work_date=target_work_date,
        shift_checkin_time=shift_checkin_time,
        timezone_name=timezone_name,
    )

    valid_clock = window_clock_times_utc[0] if window_clock_times_utc else None
    if valid_clock is not None:
        if valid_clock > (scheduled_utc + tol):
            return AuditDecision(result=AUDIT_RESULT_LATE, valid_clock_time_utc=valid_clock, is_terminal=True)
        return AuditDecision(result=AUDIT_RESULT_NORMAL, valid_clock_time_utc=valid_clock, is_terminal=True)

    # 缺卡：未到最终缺卡判定时点时，保持 NONE（未终态，允许后续刷新）
    win = compute_checkin_window_utc(
        target_work_date=target_work_date,
        shift_checkin_time=shift_checkin_time,
        timezone_name=timezone_name,
        attendance_flex_interval=attendance_flex_interval,
    )
    final_absent_at = win.end_utc + tol
    if now_utc >= final_absent_at:
        return AuditDecision(result=AUDIT_RESULT_ABSENT, valid_clock_time_utc=None, is_terminal=True)
    return AuditDecision(result=AUDIT_RESULT_NONE, valid_clock_time_utc=None, is_terminal=False)


def decide_checkout(
    *,
    now_utc: datetime,
    target_work_date: date,
    shift_checkin_time: object,
    shift_checkout_time: object,
    timezone_name: str,
    is_overnight: bool,
    attendance_flex_interval: object,
    max_late_early_tolerance: object,
    is_on_leave: bool,
    is_temporary_leave_covering: bool,
    is_exempt: bool,
    # 该员工在“有效窗口内”的打卡时间序列（UTC，升序）
    window_clock_times_utc: Sequence[datetime],
) -> AuditDecision:
    """
    CHECKOUT 判定：
    - 只取有效窗口内最晚打卡
    - 优先级：ON_LEAVE > TEMPORARY_LEAVE > EXEMPT > 打卡判定
    """
    if is_on_leave:
        return AuditDecision(result=AUDIT_RESULT_ON_LEAVE, valid_clock_time_utc=None, is_terminal=True)
    if is_temporary_leave_covering:
        return AuditDecision(result=AUDIT_RESULT_TEMPORARY_LEAVE, valid_clock_time_utc=None, is_terminal=True)
    if is_exempt:
        return AuditDecision(result=AUDIT_RESULT_EXEMPT, valid_clock_time_utc=None, is_terminal=True)

    tol = _to_timedelta(max_late_early_tolerance)
    scheduled_utc = _scheduled_checkout_instant_utc(
        target_work_date=target_work_date,
        shift_checkout_time=shift_checkout_time,
        timezone_name=timezone_name,
        is_overnight=is_overnight,
    )

    valid_clock = window_clock_times_utc[-1] if window_clock_times_utc else None
    if valid_clock is not None:
        if valid_clock < (scheduled_utc - tol):
            return AuditDecision(result=AUDIT_RESULT_EARLY_LEAVE, valid_clock_time_utc=valid_clock, is_terminal=True)
        return AuditDecision(result=AUDIT_RESULT_NORMAL, valid_clock_time_utc=valid_clock, is_terminal=True)

    win = compute_checkout_window_utc(
        target_work_date=target_work_date,
        shift_checkin_time=shift_checkin_time,
        shift_checkout_time=shift_checkout_time,
        timezone_name=timezone_name,
        is_overnight=is_overnight,
        attendance_flex_interval=attendance_flex_interval,
    )
    final_absent_at = win.end_utc + tol
    if now_utc >= final_absent_at:
        return AuditDecision(result=AUDIT_RESULT_ABSENT, valid_clock_time_utc=None, is_terminal=True)
    return AuditDecision(result=AUDIT_RESULT_NONE, valid_clock_time_utc=None, is_terminal=False)

