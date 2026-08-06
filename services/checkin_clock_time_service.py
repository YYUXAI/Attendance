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


_PM_PERIODS = frozenset({"下午", "晚上", "傍晚"})
_AM_PERIODS = frozenset({"上午", "早上", "凌晨"})


def _infer_chinese_period_from_raw(*, clock_time: str, raw_text: str) -> str:
    """从 AI 原文中推断上午/下午（Google 北京时间页常见「下午6:40」）。"""
    raw = raw_text or ""
    ct = (clock_time or "").strip()
    if not ct or not raw:
        return ""
    parts = ct.split(":")
    if len(parts) < 2:
        return ""
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return ""
    flex_patterns = [
        rf"{hour}:{minute:02d}",
        rf"{hour:02d}:{minute:02d}",
    ]
    if hour < 10:
        flex_patterns.append(rf"0?{hour}:{minute:02d}")

    for period in _PM_PERIODS | _AM_PERIODS:
        if period not in raw:
            continue
        for fp in flex_patterns:
            if re.search(rf"{period}\s*{re.escape(fp)}", raw):
                return period
            if re.search(rf"{period}{re.escape(fp)}", raw):
                return period

    if any(p in raw for p in _PM_PERIODS) and 1 <= hour <= 11:
        return "下午"
    if any(p in raw for p in _AM_PERIODS) and 1 <= hour <= 12:
        return "上午"
    return ""


def resolve_remote_diff_clock_time(
    *,
    clock_time: str | None,
    clock_period: str | None = None,
    raw_text: str | None = None,
    reference_utc: datetime | None = None,
    shift_timezone: str = "Asia/Shanghai",
    max_skew_minutes: int = 30,
) -> str | None:
    """
    remote_diff 专用：识别上午/下午并统一为 24 小时制。
    若 AI 只返回 6:40 但发送时刻为 18:41，会在偏差约 12 小时时按下午校正。
    即使 AI 错填 clock_period=上午，只要 ±12 小时能贴近发图时间，仍优先纠正。
    """
    ct = (clock_time or "").strip()
    if not ct:
        return None

    period = (clock_period or "").strip()
    for p in _PM_PERIODS | _AM_PERIODS:
        if p in period:
            period = p
            break
    else:
        period = _infer_chinese_period_from_raw(clock_time=ct, raw_text=raw_text or "")

    period_normed: str | None = None
    if period and period not in ct:
        period_normed = normalize_clock_time_text(f"{period}{ct.lstrip()}")

    plain_normed = normalize_clock_time_text(ct)
    normed = period_normed or plain_normed
    if not normed or reference_utc is None:
        return normed

    try:
        tz = ZoneInfo(shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai")
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    ref = reference_utc if reference_utc.tzinfo else reference_utc.replace(tzinfo=timezone.utc)
    ref_local = ref.astimezone(tz)

    def _skew_minutes(candidate: str) -> float | None:
        t = _parse_clock_time(candidate)
        if t is None:
            return None
        work_date = ref_local.date()
        local_dt = datetime.combine(work_date, t, tzinfo=tz)
        return abs((local_dt.astimezone(timezone.utc) - ref).total_seconds()) / 60.0

    def _flip_12h(candidate: str) -> str | None:
        parts = candidate.split(":")
        if len(parts) < 2:
            return None
        try:
            hour = int(parts[0])
        except ValueError:
            return None
        rest = ":".join(parts[1:])
        if hour < 12:
            return normalize_clock_time_text(f"下午{hour}:{rest}")
        if hour == 12:
            return normalize_clock_time_text(f"上午12:{rest}")
        return normalize_clock_time_text(f"上午{hour - 12}:{rest}")

    # 先收集候选：period 结果、原文纯时间、以及各自的 ±12 小时翻转
    candidates: list[str] = []
    for c in (normed, plain_normed):
        if c and c not in candidates:
            candidates.append(c)
        if c:
            flipped = _flip_12h(c)
            if flipped and flipped not in candidates:
                candidates.append(flipped)

    best: str | None = None
    best_skew: float | None = None
    for c in candidates:
        sk = _skew_minutes(c)
        if sk is None:
            continue
        if sk <= max_skew_minutes and (best_skew is None or sk < best_skew):
            best = c
            best_skew = sk
    if best is not None:
        return best

    return normed


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
_MONTH_DAY_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
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


def _format_month_day(month: int, day: int) -> str:
    return f"{month:02d}-{day:02d}"


def _valid_month_day(month: int, day: int) -> bool:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    try:
        date(2000, month, day)
    except ValueError:
        return False
    return True


def parse_clock_month_day(raw: str | None) -> tuple[int, int] | None:
    """解析 MM-DD 或 YYYY-MM-DD，只返回 (month, day)。"""
    s = (raw or "").strip()
    if not s:
        return None
    m = _MONTH_DAY_RE.match(s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        return (month, day) if _valid_month_day(month, day) else None
    iso = normalize_clock_date_iso(s)
    if not iso:
        return None
    full = _parse_clock_date_strict(iso)
    if full is None:
        return None
    return full.month, full.day


def normalize_clock_date_month_day(raw: str | None) -> str | None:
    """将日期规范为 MM-DD（打卡字段标准格式，不含年份）。"""
    md = parse_clock_month_day(raw)
    if md is None:
        return None
    return _format_month_day(md[0], md[1])


def normalize_clock_date_iso(raw: str | None) -> str | None:
    """将 YYYY-MM-DD 规范为公历；佛历 25xx 年自动减 543（2569-06-19 → 2026-06-19）。"""
    s = (raw or "").strip()
    if not s:
        return None
    m = _DATE_RE.match(s)
    if not m:
        dm = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
        if not dm:
            return None
        y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
    else:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    gy = _gregorian_year_from_ocr_year(y)
    if not (2000 <= gy <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    try:
        date(gy, mo, d)
    except ValueError:
        return None
    return f"{gy}-{mo:02d}-{d:02d}"


def _date_from_buddhist_match(m: re.Match[str]) -> str:
    month, day = int(m.group(2)), int(m.group(3))
    return _format_month_day(month, day)


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
    返回 MM-DD；支持佛历/公历中文日期行与 YYYY-MM-DD。
    """
    if not text:
        return None
    normalized = normalize_ocr_date_text(text, expected_date=expected_date).replace("\n", " ")
    buddhist = _extract_buddhist_date(normalized)
    if buddhist:
        return buddhist
    m_cn = _CHINESE_GREGORIAN_DATE_RE.search(normalized)
    if m_cn:
        return _format_month_day(int(m_cn.group(2)), int(m_cn.group(3)))
    dm = _ISO_DATE_IN_TEXT_RE.search(normalized)
    if dm:
        return normalize_clock_date_month_day(dm.group(1))
    return None


def date_matches_expected_month_day(*, clock_date: str | None, expected_date: str) -> bool:
    exp = _parse_clock_date_strict(expected_date)
    cur_md = parse_clock_month_day(clock_date)
    if exp is None or cur_md is None:
        return False
    return cur_md == (exp.month, exp.day)


def reconcile_clock_date(
    *,
    clock_date: str | None,
    raw_text: str,
    expected_date: str,
) -> str | None:
    """
    从模型原文纠正智谱误读的日期（如 6/22 读成 6/19）。
    返回与 expected_date 月日一致的 MM-DD；无法纠正时返回规范化后的原值。
    """
    exp = _parse_clock_date_strict(expected_date)
    norm = normalize_clock_date_month_day(clock_date)
    if exp is not None and norm:
        cur_md = parse_clock_month_day(norm)
        if cur_md == (exp.month, exp.day):
            return norm

    sources: list[str] = []
    if raw_text:
        sources.append(raw_text)

    for text in sources:
        parsed = extract_clock_date_from_text(text, expected_date=expected_date)
        if not parsed:
            continue
        parsed_md = parse_clock_month_day(parsed)
        if parsed_md is not None and exp is not None and parsed_md == (exp.month, exp.day):
            return parsed

    # 智谱仅 JSON 误读日（如 6/22→6/19），且原文无中文日期行时，采纳发消息当天月日
    has_cn_date_line = any(
        _BUDDHIST_DATE_RE.search(t)
        or _BUDDHIST_LOOSE_RE.search(t)
        or _CHINESE_GREGORIAN_DATE_RE.search(t)
        for t in sources
    )
    if not has_cn_date_line and exp is not None and norm:
        cur_md = parse_clock_month_day(norm)
        if cur_md is not None and cur_md[0] == exp.month and cur_md != (exp.month, exp.day):
            return _format_month_day(exp.month, exp.day)
    return norm


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
    parsed_md = parse_clock_month_day(parsed) if parsed else None
    if parsed_md is not None and exp_dt is not None and parsed_md == (exp_dt.month, exp_dt.day):
        return parsed
    llm = normalize_clock_date_month_day(llm_clock_date)
    llm_md = parse_clock_month_day(llm) if llm else None
    if llm_md is not None and exp_dt is not None and llm_md == (exp_dt.month, exp_dt.day):
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
    cur_md = parse_clock_month_day(extraction.clock_date)
    if cur_md is None:
        return "missing" if require_date else "ok"
    # 业务要求：日期仅校验月/日，不校验年份
    if cur_md != (expected.month, expected.day):
        return "mismatch"
    return "ok"


def evaluate_clock_time(
    *,
    extraction: CheckinImageExtraction,
    shift_timezone: str,
    now_utc: datetime,
    max_skew_minutes: int,
    raw_text: str | None = None,
) -> tuple[ClockTimeStatus, Optional[datetime]]:
    if not extraction.clock_time:
        return "missing", None

    ref = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    resolved = resolve_remote_diff_clock_time(
        clock_time=extraction.clock_time,
        clock_period=None,
        raw_text=raw_text or "",
        reference_utc=ref,
        shift_timezone=shift_timezone,
        max_skew_minutes=max_skew_minutes,
    )
    if not resolved:
        return "invalid_format", None
    t = _parse_clock_time(resolved)
    if t is None:
        return "invalid_format", None

    tz_name = _resolve_timezone(extraction, shift_timezone)
    tz = ZoneInfo(tz_name)
    local_now = ref.astimezone(tz)
    cur_md = parse_clock_month_day(extraction.clock_date)
    if cur_md is not None:
        work_date = date(local_now.year, cur_md[0], cur_md[1])
    else:
        work_date = local_now.date()

    local_dt = datetime.combine(work_date, t, tzinfo=tz)
    clock_utc = local_dt.astimezone(timezone.utc)

    skew_sec = abs((clock_utc - ref).total_seconds())
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
