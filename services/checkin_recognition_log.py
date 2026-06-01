from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from domain.checkin_image_extraction import CheckinImageExtraction

log = logging.getLogger(__name__)


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
