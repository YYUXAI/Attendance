from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

from domain.clock_matter import ACTION_SIGN_IN, ACTION_SIGN_OUT


@dataclass(frozen=True)
class PunchAt:
    at: datetime
    action: str | None


def is_overnight_shift(*, checkin: time, checkout: time) -> bool:
    return checkout <= checkin


def _local_dt(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    return dt.astimezone(tz)


def _evening_checkins_on_day(
    punches: Sequence[PunchAt],
    *,
    day: date,
    checkin: time,
    tz: ZoneInfo,
) -> list[datetime]:
    """跨夜班：当日 evening 段（本地时刻 >= 上班时间）的签到。"""
    out: list[datetime] = []
    for p in punches:
        if p.action != ACTION_SIGN_IN:
            continue
        local = _local_dt(p.at, tz)
        if local.date() != day:
            continue
        if local.timetz().replace(tzinfo=None) >= checkin:
            out.append(p.at)
    return out


def _morning_checkouts_on_day(
    punches: Sequence[PunchAt],
    *,
    day: date,
    checkin: time,
    tz: ZoneInfo,
) -> list[datetime]:
    """跨夜班：当日 morning 段（本地时刻 < 上班时间）的签退，归属前一逻辑工作日下班。"""
    out: list[datetime] = []
    for p in punches:
        if p.action != ACTION_SIGN_OUT:
            continue
        local = _local_dt(p.at, tz)
        if local.date() != day:
            continue
        if local.timetz().replace(tzinfo=None) < checkin:
            out.append(p.at)
    return out


def had_evening_checkin_on_day(
    punches: Sequence[PunchAt],
    *,
    day: date,
    checkin: time,
    tz: ZoneInfo,
) -> bool:
    return bool(_evening_checkins_on_day(punches, day=day, checkin=checkin, tz=tz))


def evaluate_calendar_day_status(
    *,
    day: date,
    checkin: time,
    checkout: time,
    tz_name: str,
    rest_days: set[int],
    punches_today: Sequence[PunchAt],
    punches_yesterday: Sequence[PunchAt],
) -> tuple[str, datetime | None, datetime | None]:
    """
    按「日历日」判定考勤状态与展示用的上/下班打卡时刻。

    跨夜班（如 18:00–次日 03:00）：
    - 班次开始日：只要求打「上班卡」（ evening 签到），缺下班卡不算缺卡。
    - 次日起及以后每个工作日：早上打「上一班下班卡」+  evening 「本班上班卡」。
    - 仅当昨日 evening 有签到时，才要求今日 morning 签退。

    非跨夜班：当日需签到+签退，与班次时间比迟到/早退。

    返回 (status, checkin_display_utc, checkout_display_utc)。
    """
    tz = ZoneInfo(tz_name)
    if day.day in rest_days:
        return "月休", None, None

    overnight = is_overnight_shift(checkin=checkin, checkout=checkout)
    scheduled_in = datetime.combine(day, checkin, tzinfo=tz)

    if not overnight:
        sign_ins: list[datetime] = []
        sign_outs: list[datetime] = []
        for p in punches_today:
            local = _local_dt(p.at, tz)
            if local.date() != day:
                continue
            if p.action == ACTION_SIGN_IN:
                sign_ins.append(p.at)
            elif p.action == ACTION_SIGN_OUT:
                sign_outs.append(p.at)
        checkin_utc = min(sign_ins) if sign_ins else None
        checkout_utc = max(sign_outs) if sign_outs else None
        scheduled_out = datetime.combine(day, checkout, tzinfo=tz)
        return _status_from_expected(
            expect_checkin=True,
            expect_checkout=True,
            checkin_utc=checkin_utc,
            checkout_utc=checkout_utc,
            scheduled_in=scheduled_in,
            scheduled_out=scheduled_out,
            tz=tz,
        )

    # --- 跨夜班 ---
    prev_day = day - timedelta(days=1)
    prev_was_rest = prev_day.day in rest_days
    had_prev_evening = (
        not prev_was_rest
        and had_evening_checkin_on_day(
            punches_yesterday,
            day=prev_day,
            checkin=checkin,
            tz=tz,
        )
    )

    evening_ins = _evening_checkins_on_day(punches_today, day=day, checkin=checkin, tz=tz)
    morning_outs = _morning_checkouts_on_day(punches_today, day=day, checkin=checkin, tz=tz)
    today_checkin = min(evening_ins) if evening_ins else None
    prev_checkout = max(morning_outs) if morning_outs else None

    expect_checkin = True
    expect_checkout = had_prev_evening
    scheduled_out = datetime.combine(day, checkout, tzinfo=tz)

    return _status_from_expected(
        expect_checkin=expect_checkin,
        expect_checkout=expect_checkout,
        checkin_utc=today_checkin,
        checkout_utc=prev_checkout,
        scheduled_in=scheduled_in,
        scheduled_out=scheduled_out,
        tz=tz,
    )


def _status_from_expected(
    *,
    expect_checkin: bool,
    expect_checkout: bool,
    checkin_utc: datetime | None,
    checkout_utc: datetime | None,
    scheduled_in: datetime,
    scheduled_out: datetime,
    tz: ZoneInfo,
) -> tuple[str, datetime | None, datetime | None]:
    missing_in = expect_checkin and checkin_utc is None
    missing_out = expect_checkout and checkout_utc is None

    if not expect_checkin and not expect_checkout:
        return "缺卡", checkin_utc, checkout_utc

    if not checkin_utc and not checkout_utc:
        return "缺卡", None, None

    late = (
        checkin_utc is not None
        and _local_dt(checkin_utc, tz) > scheduled_in
    )
    early = (
        checkout_utc is not None
        and _local_dt(checkout_utc, tz) < scheduled_out
    )

    if missing_in or missing_out:
        if missing_in and missing_out:
            return "缺卡", checkin_utc, checkout_utc
        if missing_in:
            return ("早退", checkin_utc, checkout_utc) if early else ("缺卡", checkin_utc, checkout_utc)
        return ("迟到", checkin_utc, checkout_utc) if late else ("缺卡", checkin_utc, checkout_utc)

    if late and early:
        return "迟到+早退", checkin_utc, checkout_utc
    if late:
        return "迟到", checkin_utc, checkout_utc
    if early:
        return "早退", checkin_utc, checkout_utc
    return "正常", checkin_utc, checkout_utc
