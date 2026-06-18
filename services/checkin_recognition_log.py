from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from domain.checkin_image_extraction import CheckinImageExtraction

log = logging.getLogger(__name__)

# 智谱 JSON 里可能出现的文本字段（含 keyword retry 扩展字段）
_AI_JSON_TEXT_KEYS = (
    "display_name",
    "username_hint",
    "clock_time",
    "clock_date",
    "timezone_iana",
    "identity_text",
    "time_text",
    "date_text",
    "all_visible_text",
    "confidence",
)


def _strip_json_payload(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _parse_ai_json_dict(raw: str | None) -> dict[str, Any] | None:
    if not raw or not str(raw).strip():
        return None
    payload = _strip_json_payload(str(raw))
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        repaired = re.sub(r",\s*([}\]])", r"\1", payload)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def log_checkin_ai_text(
    *,
    phase: str,
    tg_id: int | None = None,
    raw: str | None = None,
    extraction: CheckinImageExtraction | None = None,
) -> None:
    """打印智谱/OCR 识别到的全部文本字段（grep CHECKIN_AI_TEXT）。"""
    fields: dict[str, str] = {}
    parsed = _parse_ai_json_dict(raw)
    if parsed is not None:
        for key, val in parsed.items():
            if val is None:
                fields[key] = ""
            elif isinstance(val, (str, int, float, bool)):
                fields[key] = str(val)
            else:
                fields[key] = json.dumps(val, ensure_ascii=False)
    elif raw and str(raw).strip():
        fields["raw_unparsed"] = str(raw).strip()

    if extraction is not None:
        fields["final_display_name"] = extraction.display_name or ""
        fields["final_username_hint"] = extraction.username_hint or ""
        fields["final_clock_time"] = extraction.clock_time or ""
        fields["final_clock_date"] = extraction.clock_date or ""
        fields["final_timezone_iana"] = extraction.timezone_iana or ""
        if extraction.confidence is not None:
            fields["final_confidence"] = str(extraction.confidence)

    ordered: list[str] = []
    for key in _AI_JSON_TEXT_KEYS:
        if key in fields:
            ordered.append(f"{key}={fields[key]!r}")
    for key in sorted(fields):
        if key not in _AI_JSON_TEXT_KEYS and not key.startswith("final_"):
            ordered.append(f"{key}={fields[key]!r}")
    for key in sorted(fields):
        if key.startswith("final_"):
            ordered.append(f"{key}={fields[key]!r}")

    log.info(
        "[CHECKIN_AI_TEXT] phase=%s tg_id=%s %s",
        phase,
        tg_id if tg_id is not None else "",
        " ".join(ordered) if ordered else "(empty)",
    )
    if raw and str(raw).strip():
        log.info(
            "[CHECKIN_AI_TEXT] phase=%s tg_id=%s raw_json_begin\n%s\nraw_json_end",
            phase,
            tg_id if tg_id is not None else "",
            str(raw).strip(),
        )


def log_checkin_recognition(
    *,
    stage: str,
    tg_id: int,
    extraction: CheckinImageExtraction | None = None,
    expected_username: str | None = None,
    expected_english_name: str | None = None,
    employee_id: str | None = None,
    composite_screenshot: bool | None = None,
    error_code: str | None = None,
    clock_time_utc: datetime | None = None,
    shift_timezone: str = "Asia/Shanghai",
    matter: str | None = None,
) -> None:
    """将截图识别与校验关键字段写入终端日志（grep CHECKIN_RECOGNIZE）。"""
    ext = extraction
    clock_local = ""
    if clock_time_utc is not None:
        try:
            clock_local = clock_time_utc.astimezone(ZoneInfo(shift_timezone)).strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
        except Exception:
            clock_local = str(clock_time_utc)

    log.info(
        "[CHECKIN_RECOGNIZE] stage=%s tg_id=%s employee_id=%s composite=%s "
        "ocr_name=%r ocr_hint=%r ocr_time=%r ocr_date=%r ocr_tz=%r "
        "expected_user=%r expected_name=%r matter=%r error=%s clock_utc=%s clock_local=%s",
        stage,
        tg_id,
        employee_id or "",
        composite_screenshot,
        (ext.display_name if ext else None),
        (ext.username_hint if ext else None),
        (ext.clock_time if ext else None),
        (ext.clock_date if ext else None),
        (ext.timezone_iana if ext else None),
        expected_username,
        expected_english_name,
        matter,
        error_code or "",
        clock_time_utc.isoformat() if clock_time_utc else "",
        clock_local,
    )
