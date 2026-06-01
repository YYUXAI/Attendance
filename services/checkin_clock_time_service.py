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


def extract_clock_date_from_text(text: str) -> Optional[str]:
    """
    从 OCR 文本解析打卡日期（不用数字模糊拼接）。
    佛历 25xx年M月D日、公历 20xx年M月D日、YYYY-MM-DD。
    """
    if not text:
        return None
    normalized = text.replace("\n", " ")
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
    parsed = extract_clock_date_from_text(text)
    if parsed == expected_date:
        return parsed
    llm = (llm_clock_date or "").strip()
    if llm == expected_date and _parse_clock_date_strict(llm) is not None:
        return llm
    if parsed and parsed != expected_date:
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
    if parsed != expected:
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
