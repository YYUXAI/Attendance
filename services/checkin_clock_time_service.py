from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from domain.checkin_image_extraction import CheckinImageExtraction
from services.checkin_service import ALLOWED_TIMEZONES

ClockTimeStatus = Literal["ok", "missing", "invalid_format", "skew", "date_missing", "date_mismatch"]
ClockDateStatus = Literal["ok", "missing", "mismatch"]

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_CHINESE_AMPM_CLOCK_RE = re.compile(
    r"^(上午|早上|凌晨|下午|晚上|傍晚)\s*(\d{1,2})\s*:\s*(\d{2})(?:\s*:\s*(\d{2}))?$"
)
_CLOCK_FRAGMENT_RE = re.compile(
    r"((?:上午|早上|凌晨|下午|晚上|傍晚)\s*)?(\d{1,2})\s*:\s*(\d{2})(?:\s*:\s*(\d{2}))?"
)


def _clock_hms_to_str(hour: int, minute: int, second: int) -> str:
    if second:
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    return f"{hour:02d}:{minute:02d}"


def _apply_chinese_period(*, period: str, hour: int) -> int | None:
    if period in ("下午", "晚上", "傍晚"):
        return hour + 12 if hour < 12 else hour
    if period in ("上午", "早上", "凌晨"):
        return 0 if hour == 12 else hour
    return hour


def normalize_clock_time_text(value: str) -> Optional[str]:
    """将 03:04:01、上午3:04 等统一为 24 小时 HH:MM 或 HH:MM:SS。"""
    s = (value or "").strip()
    if not s:
        return None

    m = _TIME_RE.match(s)
    if m:
        hour, minute, second = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if hour > 23 or minute > 59 or second > 59:
            return None
        return _clock_hms_to_str(hour, minute, second)

    m = _CHINESE_AMPM_CLOCK_RE.match(s)
    if m:
        period = m.group(1)
        hour, minute = int(m.group(2)), int(m.group(3))
        second = int(m.group(4) or 0)
        if minute > 59 or second > 59:
            return None
        hour = _apply_chinese_period(period=period, hour=hour)
        if hour is None or hour > 23:
            return None
        return _clock_hms_to_str(hour, minute, second)

    for m in _CLOCK_FRAGMENT_RE.finditer(s):
        period = (m.group(1) or "").strip()
        hour, minute = int(m.group(2)), int(m.group(3))
        second = int(m.group(4) or 0)
        if minute > 59 or second > 59:
            continue
        if period:
            hour = _apply_chinese_period(period=period, hour=hour)
            if hour is None or hour > 23:
                continue
        elif hour > 23:
            continue
        return _clock_hms_to_str(hour, minute, second)

    return None


def clock_time_grounded_in_raw(clock_time: str, raw: str) -> bool:
    """规范化时钟须在模型 JSON 原文中有可对应片段（含上午/下午写法）。"""
    if not clock_time or not raw:
        return False
    if clock_time in raw:
        return True
    parts = clock_time.split(":")
    if len(parts) >= 2:
        try:
            flex = f"{int(parts[0])}:{parts[1]}"
            if flex in raw:
                return True
            if len(parts) >= 3:
                flex_sec = f"{int(parts[0])}:{parts[1]}:{parts[2]}"
                if flex_sec in raw:
                    return True
        except ValueError:
            pass
    target = normalize_clock_time_text(clock_time)
    if not target:
        return False
    for m in _CLOCK_FRAGMENT_RE.finditer(raw):
        if normalize_clock_time_text(m.group(0)) == target:
            return True
    return False
_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_ISO_DATE_IN_TEXT_RE = re.compile(r"\b(20\d{2}-\d{1,2}-\d{1,2})\b")
# TIME.IS 佛历：佛历2569年6月1日；OCR 可能用全角括号、粘连无空格
_BUDDHIST_DATE_RE = re.compile(
    r"佛[历曆]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
_BUDDHIST_LOOSE_RE = re.compile(
    r"(?:佛[历曆]?\s*)?(25\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
# 公历中文（仅 20xx 年，与佛历 25xx 区分）
_CHINESE_GREGORIAN_DATE_RE = re.compile(
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
# OCR 常把「4日」连成两位数字：6月48、6月41 → 6月4日
_MONTH_DAY_GLITCH_RE = re.compile(r"(\d{1,2})月(\d{2})(?!日|\d)")


def _gregorian_year_from_ocr_year(year: int) -> int:
    """佛历 25xx 转公历（减 543）；20xx 原样返回。"""
    if 2500 <= year <= 2599:
        return year - 543
    return year


def _date_from_buddhist_match(m: re.Match[str]) -> str:
    gy = _gregorian_year_from_ocr_year(int(m.group(1)))
    return f"{gy}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _extract_buddhist_date(normalized: str) -> Optional[str]:
    for pattern in (_BUDDHIST_DATE_RE, _BUDDHIST_LOOSE_RE):
        m = pattern.search(normalized)
        if m:
            return _date_from_buddhist_match(m)
    return None


def _expected_month_day(expected_date: str | None) -> tuple[int, int] | None:
    if not expected_date:
        return None
    m = _DATE_RE.match(expected_date.strip())
    if not m:
        return None
    return int(m.group(2)), int(m.group(3))


def _fix_glued_month_day(*, month: int, day: int, expected_md: tuple[int, int] | None) -> int | None:
    """
    TIME.IS 常见 OCR：「D日」粘成两位数字末尾 8。
    - 4日→48（>31，直接取十位）
    - 1日→18、2日→28、3日→38（需与发消息日 expected 一致才改，避免真 18 号被误伤）
    """
    if day > 31:
        fixed = day // 10
        return fixed if 1 <= fixed <= 31 else None
    if day % 10 == 8 and 18 <= day <= 38:
        fixed = day // 10
        if not (1 <= fixed <= 31):
            return None
        if expected_md is None:
            return None
        exp_month, exp_day = expected_md
        if exp_month == month and exp_day == fixed:
            return fixed
    return None


def normalize_ocr_date_text(text: str, *, expected_date: str | None = None) -> str:
    """修正 OCR 日期粘连：几月几日被读成 月48、月18 等。"""
    expected_md = _expected_month_day(expected_date)

    def _fix_month_day(m: re.Match[str]) -> str:
        month, day = int(m.group(1)), int(m.group(2))
        fixed = _fix_glued_month_day(month=month, day=day, expected_md=expected_md)
        if fixed is not None:
            return f"{month}月{fixed}日"
        return m.group(0)

    return _MONTH_DAY_GLITCH_RE.sub(_fix_month_day, text or "")


def extract_clock_date_from_text(text: str, *, expected_date: str | None = None) -> Optional[str]:
    """
    从 OCR 文本解析打卡日期（不用数字模糊拼接）。
    佛历 25xx年M月D日、公历 20xx年M月D日、YYYY-MM-DD。
    """
    if not text:
        return None
    normalized = normalize_ocr_date_text(text, expected_date=expected_date).replace("\n", " ")
    buddhist = _extract_buddhist_date(normalized)
    if buddhist:
        return buddhist
    m_cn = _CHINESE_GREGORIAN_DATE_RE.search(normalized)
    if m_cn:
        return f"{m_cn.group(1)}-{int(m_cn.group(2)):02d}-{int(m_cn.group(3)):02d}"
    dm = _ISO_DATE_IN_TEXT_RE.search(normalized)
    if dm:
        return dm.group(1)
    return None


def extract_clock_date_for_checkin(
    text: str,
    *,
    expected_date: str,
    llm_clock_date: str | None = None,
) -> Optional[str]:
    """
    打卡用：优先 OCR 规则；规则未命中时，若 LLM 日期等于发消息当天也可采用。
    """
    parsed = extract_clock_date_from_text(text, expected_date=expected_date)
    exp_dt = _parse_clock_date_strict(expected_date)
    parsed_dt = _parse_clock_date_strict(parsed) if parsed else None
    if parsed_dt is not None and exp_dt is not None and _same_month_day(parsed_dt, exp_dt):
        return parsed
    llm = (llm_clock_date or "").strip()
    llm_dt = _parse_clock_date_strict(llm) if llm else None
    if llm_dt is not None and exp_dt is not None and _same_month_day(llm_dt, exp_dt):
        return llm
    if parsed:
        return None
    return None


def _resolve_timezone(extraction: CheckinImageExtraction, shift_timezone: str) -> str:
    tz = (extraction.timezone_iana or "").strip()
    if tz in ALLOWED_TIMEZONES:
        return tz
    return shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai"


def _parse_clock_time(clock_time: str) -> Optional[time]:
    m = _TIME_RE.match(clock_time.strip())
    if not m:
        return None
    h, mi, sec = int(m.group(1)), int(m.group(2)), int(m.group(3) or "0")
    if h > 23 or mi > 59 or sec > 59:
        return None
    return time(h, mi, sec)


def _parse_clock_date(clock_date: str, *, fallback: date) -> date:
    m = _DATE_RE.match(clock_date.strip())
    if not m:
        return fallback
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return fallback


def _parse_clock_date_strict(clock_date: str) -> Optional[date]:
    m = _DATE_RE.match(clock_date.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _same_month_day(a: date, b: date) -> bool:
    return a.month == b.month and a.day == b.day


def evaluate_clock_date(
    *,
    extraction: CheckinImageExtraction,
    shift_timezone: str,
    now_utc: datetime,
    require_date: bool = False,
) -> ClockDateStatus:
    tz_name = _resolve_timezone(extraction, shift_timezone)
    expected = now_utc.astimezone(ZoneInfo(tz_name)).date()
    raw = (extraction.clock_date or "").strip()
    if not raw:
        return "missing" if require_date else "ok"
    parsed = _parse_clock_date_strict(raw)
    if parsed is None:
        return "missing" if require_date else "ok"
    # 业务要求：日期仅校验月/日，不校验年份
    if not _same_month_day(parsed, expected):
        return "mismatch"
    return "ok"


def evaluate_clock_time(
    *,
    extraction: CheckinImageExtraction,
    shift_timezone: str,
    now_utc: datetime,
    max_skew_minutes: int,
) -> tuple[ClockTimeStatus, Optional[datetime]]:
    if not extraction.clock_time:
        return "missing", None
    t = _parse_clock_time(extraction.clock_time)
    if t is None:
        return "invalid_format", None

    tz_name = _resolve_timezone(extraction, shift_timezone)
    tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(tz)
    if extraction.clock_date:
        work_date = _parse_clock_date_strict(extraction.clock_date) or local_now.date()
    else:
        work_date = local_now.date()

    local_dt = datetime.combine(work_date, t, tzinfo=tz)
    clock_utc = local_dt.astimezone(timezone.utc)

    skew_sec = abs((clock_utc - now_utc).total_seconds())
    if skew_sec > max_skew_minutes * 60:
        return "skew", None
    return "ok", clock_utc


def extraction_to_clock_time_utc(
    *,
    extraction: CheckinImageExtraction,
    shift_timezone: str,
    now_utc: datetime,
    max_skew_minutes: int,
) -> Optional[datetime]:
    status, clock_utc = evaluate_clock_time(
        extraction=extraction,
        shift_timezone=shift_timezone,
        now_utc=now_utc,
        max_skew_minutes=max_skew_minutes,
    )
    if status != "ok":
        return None
    return clock_utc
