"""YYMG 班表「地区」→ 当地时区（班表上下班时间为当地时间）。"""
from __future__ import annotations

REGION_TIMEZONE: dict[str, str] = {
    "TH": "Asia/Bangkok",
    "F-KJY": "Asia/Manila",
    "DB": "Asia/Dubai",
}

# 截图打卡时间固定为北京时间
SCREENSHOT_TIMEZONE = "Asia/Shanghai"


def normalize_region_code(raw: str) -> str:
    """解析班表「地区」单元格为 TH / F-KJY / DB。"""
    text = (raw or "").strip().upper()
    if not text:
        return ""
    if text.startswith("TH") or "泰国" in raw:
        return "TH"
    if "F-KJY" in text or "KJY" in text or "菲律宾" in raw:
        return "F-KJY"
    if text.startswith("DB") or "迪拜" in raw:
        return "DB"
    for code in REGION_TIMEZONE:
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
