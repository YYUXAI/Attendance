from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from zoneinfo import ZoneInfo

from domain.shared.result import ServiceResult
from repositories import clock_records_repo, profile_repo
from services.group_attendance_summary_service import (
    _as_time,
    compute_month_stats_for_employee,
)


def _display_name_or_fallback(english_name: Optional[str]) -> str:
    """
    docs00：对外展示优先 english_name，不得用 employee_id 当人名。
    """
    raw = (english_name or "").strip()
    return raw if raw else "（未填英文名）"


def _month_range_local(*, tz_name: str, now_utc: datetime) -> tuple[date, date, ZoneInfo]:
    tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(tz)
    first = date(local_now.year, local_now.month, 1)
    if local_now.month == 12:
        next_first = date(local_now.year + 1, 1, 1)
    else:
        next_first = date(local_now.year, local_now.month + 1, 1)
    last = next_first - timedelta(days=1)
    return first, last, tz


def _shift_display_from_config(*, shift_cfg, tz_name: str) -> tuple[str, time, time, str]:
    cin = _as_time(shift_cfg.shift_checkin_time)
    cout = _as_time(shift_cfg.shift_checkout_time)
    rest_raw = str(shift_cfg.monthly_rest_days or "")
    rng = (shift_cfg.shift_time_range or "").strip()
    shift_time_display = rng if rng else f"{cin} - {cout}（{tz_name}）"
    return shift_time_display, cin, cout, rest_raw


def get_my_profile_by_tg_id(*, tg_id: int, now_utc: Optional[datetime] = None) -> ServiceResult:
    now = now_utc or datetime.now(timezone.utc)

    prof = profile_repo.get_registration_profile_by_tg_id(tg_id=tg_id)
    if not prof:
        return ServiceResult(ok=False, message="你还未完成注册，请先注册后再查看我的信息。", error_code="NOT_REGISTERED")

    english_name = _display_name_or_fallback(prof.english_name)
    employee_id = str(prof.employee_id)
    tz_name = "Asia/Shanghai"
    month_start, month_end, tz = _month_range_local(tz_name=tz_name, now_utc=now)
    as_of_local = now.astimezone(tz).date()
    year_month = month_start.strftime("%Y-%m")

    shift_cfg = profile_repo.get_employee_shift_config_for_month(
        employee_id=employee_id,
        year_month=year_month,
    )
    if not shift_cfg:
        msg = (
            f"姓名：{html.escape(english_name)}\n"
            f"工号：{html.escape(employee_id)}\n"
            "班次：未配置"
        )
        return ServiceResult(ok=True, message=msg)

    shift_time_display, cin, cout, rest_raw = _shift_display_from_config(
        shift_cfg=shift_cfg,
        tz_name=tz_name,
    )
    chat_id = clock_records_repo.get_latest_chat_id_for_employee(employee_id=employee_id)
    stats = compute_month_stats_for_employee(
        employee_id=employee_id,
        shift_id=None,
        chat_id=chat_id,
        month_start=month_start,
        month_end=month_end,
        as_of_local=as_of_local,
        checkin=cin,
        checkout=cout,
        rest_days_raw=rest_raw,
        tz_name=tz_name,
    )

    msg = (
        f"姓名：{html.escape(english_name)}\n"
        f"工号：{html.escape(employee_id)}\n"
        f"班次：{html.escape(shift_time_display)}\n"
        "-----------------------\n"
        f"本月已出勤天数：{stats.attendance_days}天\n"
        f"本月缺卡次数：{stats.missing_count}次\n"
        f"本月迟到次数：{stats.late_count}次\n"
        f"本月早退次数：{stats.early_count}次"
    )
    return ServiceResult(ok=True, message=msg)
