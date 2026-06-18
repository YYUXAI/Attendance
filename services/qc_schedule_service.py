from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from domain import audit_rules
from repositories import shifts_repo


def _interval_to_timedelta(v: object) -> timedelta:
    if isinstance(v, timedelta):
        return v
    if isinstance(v, (int, float)):
        return timedelta(minutes=float(v))
    raise TypeError(f"Unsupported qc_trigger_interval type: {type(v)!r}")


def work_date_for_shift_now(*, now_utc: datetime, shift: shifts_repo.ShiftRow) -> date:
    return audit_rules.work_date_for_shift_day(
        shift_checkin_time=shift.checkin_time,
        instant_utc=now_utc,
        timezone_name=shift.timezone,
        is_overnight=bool(shift.is_overnight),
    )


def _shift_start_end_local(*, work_date, shift: shifts_repo.ShiftRow) -> tuple[datetime, datetime]:
    tz = ZoneInfo(shift.timezone)
    checkin_t = audit_rules.as_time(shift.checkin_time)
    checkout_t = audit_rules.as_time(shift.checkout_time)
    overnight = bool(shift.is_overnight) or (checkout_t <= checkin_t)
    start_local = datetime.combine(work_date, checkin_t, tzinfo=tz)
    checkout_d = work_date + timedelta(days=1) if overnight else work_date
    end_local = datetime.combine(checkout_d, checkout_t, tzinfo=tz)
    return start_local, end_local


def shift_end_utc_for_qc_date(*, qc_date: date, shift: shifts_repo.ShiftRow) -> datetime:
    """
    班次在「已落库的 qc_date（与 qc_task_queue/qc_results 一致）」下的结束时刻（UTC）。

    使用与开轮调度相同的本地起止构造，不得另起一套日历口径。
    """
    _start_local, end_local = _shift_start_end_local(work_date=qc_date, shift=shift)
    return end_local.astimezone(timezone.utc)


def should_open_round(
    *,
    shift: shifts_repo.ShiftRow,
    work_date,
    next_round: int,
    now_utc: datetime,
) -> bool:
    """
    首轮：开班后 30 分钟；后续：qc_trigger_interval；触发时刻不得超过班次结束；当前时刻不得超过班次结束才允许新开轮。
    """
    if shift.qc_enabled is None or shift.qc_enabled is False:
        return False
    if next_round < 1:
        return False

    start_local, end_local = _shift_start_end_local(work_date=work_date, shift=shift)
    end_utc = end_local.astimezone(timezone.utc)
    if now_utc > end_utc:
        return False

    first_trigger_local = start_local + timedelta(minutes=30)
    first_trigger_utc = first_trigger_local.astimezone(timezone.utc)

    if next_round == 1:
        trigger_utc = first_trigger_utc
    else:
        if shift.qc_trigger_interval is None:
            return False
        interval = _interval_to_timedelta(shift.qc_trigger_interval)
        trigger_local = first_trigger_local + (next_round - 1) * interval
        trigger_utc = trigger_local.astimezone(timezone.utc)

    if trigger_utc > end_utc:
        return False
    return now_utc >= trigger_utc
