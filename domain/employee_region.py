"""班表「地区」→ 当地时区（表上上下班为当地墙钟）；打卡截图固定北京时间。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, time
from zoneinfo import ZoneInfo

# YYMG 长码 + QDYYZ 单字母（T/F/D/S）
REGION_TIMEZONE: dict[str, str] = {
    "TH": "Asia/Bangkok",
    "T": "Asia/Bangkok",
    "F-KJY": "Asia/Manila",
    "F": "Asia/Manila",
    "DB": "Asia/Dubai",
    "D": "Asia/Dubai",
    "S": "Asia/Colombo",
}

# 截图打卡时间固定为北京时间
SCREENSHOT_TIMEZONE = "Asia/Shanghai"


def normalize_region_code(raw: str) -> str:
    """解析班表地区单元格为规范码（TH/F-KJY/DB 或 QDYYZ 的 T/F/D/S）。"""
    text = (raw or "").strip().upper()
    if not text:
        return ""
    # QDYYZ 单字母优先（避免被 TH/DB 前缀逻辑误伤）
    if text in {"T", "F", "D", "S"}:
        return text
    if text.startswith("TH") or "泰国" in (raw or ""):
        return "TH"
    if "F-KJY" in text or "KJY" in text:
        return "F-KJY"
    if text in {"PH", "PH-K"} or text.startswith("PH") or "菲律宾" in (raw or ""):
        return "F"
    if text.startswith("DB") or "迪拜" in (raw or ""):
        return "DB"
    if (
        "兰卡" in (raw or "")
        or "斯里兰卡" in (raw or "")
        or "COLOMBO" in text
        or "SRI" in text
    ):
        return "S"
    for code in ("F-KJY", "TH", "DB"):
        if code in text:
            return code
    return text.split()[0] if text else ""


def timezone_for_region(region_code: str) -> str:
    code = normalize_region_code(region_code)
    return REGION_TIMEZONE.get(code, SCREENSHOT_TIMEZONE)


def resolve_employee_shift_timezone(
    *,
    region_code: str = "",
    shift_timezone: str = "",
    fallback: str = SCREENSHOT_TIMEZONE,
) -> str:
    tz = (shift_timezone or "").strip()
    if tz:
        return tz
    region = normalize_region_code(region_code)
    if region:
        return timezone_for_region(region)
    return fallback


def local_shift_wall_times_to_beijing(
    *,
    day: date,
    checkin: time,
    checkout: time,
    local_tz_name: str,
) -> tuple[time, time]:
    """
    表上当地墙钟班次 → 北京墙钟，供与北京打卡比对。

    跨夜班（下班时刻 ≤ 上班时刻）按当地次日下班再换算。
    """
    local_name = (local_tz_name or "").strip() or SCREENSHOT_TIMEZONE
    if local_name == SCREENSHOT_TIMEZONE:
        return checkin, checkout
    local = ZoneInfo(local_name)
    beijing = ZoneInfo(SCREENSHOT_TIMEZONE)
    start_local = datetime.combine(day, checkin, tzinfo=local)
    end_local = datetime.combine(day, checkout, tzinfo=local)
    if checkout <= checkin:
        end_local += timedelta(days=1)
    return (
        start_local.astimezone(beijing).time().replace(microsecond=0),
        end_local.astimezone(beijing).time().replace(microsecond=0),
    )
