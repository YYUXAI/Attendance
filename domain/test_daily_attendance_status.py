from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from domain.clock_matter import ACTION_SIGN_IN, ACTION_SIGN_OUT
from domain.daily_attendance_status import PunchAt, evaluate_calendar_day_status, is_midnight_noon_shift


def _utc(y, m, d, h, mi, s=0) -> datetime:
    return datetime(y, m, d, h, mi, s, tzinfo=timezone.utc)


def test_is_midnight_noon_shift() -> None:
    assert is_midnight_noon_shift(checkin=time(0, 0), checkout=time(12, 0))
    assert not is_midnight_noon_shift(checkin=time(6, 0), checkout=time(18, 0))


def test_midnight_noon_normal_day() -> None:
    """00~12 班：前日晚签到 + 当日中午签退 → 正常。"""
    day = date(2026, 7, 2)
    punches_yesterday = [
        PunchAt(at=_utc(2026, 7, 1, 4, 13, 44), action=ACTION_SIGN_OUT),
        PunchAt(at=_utc(2026, 7, 1, 15, 41, 57), action=ACTION_SIGN_IN),
    ]
    punches_today = [
        PunchAt(at=_utc(2026, 7, 2, 4, 6, 43), action=ACTION_SIGN_OUT),
        PunchAt(at=_utc(2026, 7, 2, 15, 43, 45), action=ACTION_SIGN_IN),
    ]
    status, _, _ = evaluate_calendar_day_status(
        day=day,
        checkin=time(0, 0),
        checkout=time(12, 0),
        tz_name="Asia/Manila",
        rest_days=set(),
        punches_today=punches_today,
        punches_yesterday=punches_yesterday,
        prev_checkin=time(0, 0),
        prev_checkout=time(12, 0),
        prev_was_rest=False,
    )
    assert status == "正常"


def test_midnight_noon_evening_signin_not_same_day() -> None:
    """当日 23:xx 签到归属次日，不应拉低当日状态。"""
    day = date(2026, 7, 3)
    punches_yesterday = [
        PunchAt(at=_utc(2026, 7, 2, 4, 11, 59), action=ACTION_SIGN_OUT),
        PunchAt(at=_utc(2026, 7, 2, 15, 57, 53), action=ACTION_SIGN_IN),
    ]
    punches_today = [
        PunchAt(at=_utc(2026, 7, 3, 4, 8, 31), action=ACTION_SIGN_OUT),
    ]
    status, _, _ = evaluate_calendar_day_status(
        day=day,
        checkin=time(0, 0),
        checkout=time(12, 0),
        tz_name="Asia/Manila",
        rest_days=set(),
        punches_today=punches_today,
        punches_yesterday=punches_yesterday,
        prev_checkin=time(0, 0),
        prev_checkout=time(12, 0),
        prev_was_rest=False,
    )
    assert status == "正常"


def test_midnight_noon_early_leave() -> None:
    """当日中午前签退且早于 12:00 → 早退。"""
    day = date(2026, 7, 2)
    punches_yesterday = [
        PunchAt(at=_utc(2026, 7, 1, 15, 41, 57), action=ACTION_SIGN_IN),
    ]
    punches_today = [
        PunchAt(at=_utc(2026, 7, 2, 3, 30, 0), action=ACTION_SIGN_OUT),
    ]
    status, _, _ = evaluate_calendar_day_status(
        day=day,
        checkin=time(0, 0),
        checkout=time(12, 0),
        tz_name="Asia/Manila",
        rest_days=set(),
        punches_today=punches_today,
        punches_yesterday=punches_yesterday,
        prev_checkin=time(0, 0),
        prev_checkout=time(12, 0),
        prev_was_rest=False,
    )
    assert status == "早退"


def test_day_shift_still_uses_same_day_pairing() -> None:
    """06~18 白班逻辑不受影响。"""
    day = date(2026, 7, 2)
    punches_today = [
        PunchAt(at=_utc(2026, 7, 2, 0, 30, 0), action=ACTION_SIGN_IN),
        PunchAt(at=_utc(2026, 7, 2, 9, 0, 0), action=ACTION_SIGN_OUT),
    ]
    status, _, _ = evaluate_calendar_day_status(
        day=day,
        checkin=time(6, 0),
        checkout=time(18, 0),
        tz_name="Asia/Manila",
        rest_days=set(),
        punches_today=punches_today,
        punches_yesterday=[],
        prev_checkin=time(6, 0),
        prev_checkout=time(18, 0),
        prev_was_rest=False,
    )
    assert status == "迟到+早退"


def test_overnight_to_day_shift_morning_checkout_not_day_shift_out() -> None:
    """WG→G 换班：凌晨签退是前日跨夜班下班卡，不计入当日 G 班签退。"""
    day = date(2026, 7, 21)
    punches_yesterday = [
        PunchAt(at=_utc(2026, 7, 20, 5, 31, 23), action=ACTION_SIGN_IN),
    ]
    punches_today = [
        PunchAt(at=_utc(2026, 7, 20, 18, 6, 25), action=ACTION_SIGN_OUT),
        PunchAt(at=_utc(2026, 7, 21, 5, 31, 24), action=ACTION_SIGN_IN),
    ]
    status, _, _ = evaluate_calendar_day_status(
        day=day,
        checkin=time(13, 0),
        checkout=time(22, 0),
        tz_name="Asia/Bangkok",
        rest_days=set(),
        punches_today=punches_today,
        punches_yesterday=punches_yesterday,
        prev_checkin=time(13, 0),
        prev_checkout=time(1, 0),
        prev_was_rest=False,
    )
    assert status == "缺卡"


def test_overnight_morning_checkout_uses_prev_day_shift_end() -> None:
    """跨夜班换班日：早上签退按昨日班次下班时间比，不误判早退。"""
    day = date(2026, 7, 9)
    punches_yesterday = [
        PunchAt(at=_utc(2026, 7, 8, 5, 51, 0), action=ACTION_SIGN_IN),
    ]
    punches_today = [
        PunchAt(at=_utc(2026, 7, 8, 18, 4, 27), action=ACTION_SIGN_OUT),
        PunchAt(at=_utc(2026, 7, 9, 6, 48, 0), action=ACTION_SIGN_IN),
    ]
    status, _, _ = evaluate_calendar_day_status(
        day=day,
        checkin=time(14, 0),
        checkout=time(2, 0),
        tz_name="Asia/Bangkok",
        rest_days=set(),
        punches_today=punches_today,
        punches_yesterday=punches_yesterday,
        prev_checkin=time(13, 0),
        prev_checkout=time(1, 0),
        prev_was_rest=False,
    )
    assert status == "正常"
