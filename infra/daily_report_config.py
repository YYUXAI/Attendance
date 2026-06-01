from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DailyReportConfig:
    enabled: bool
    report_hour: int
    report_minute: int
    timezone_name: str
    notify_tg_id: int | None
    notify_username: str


@dataclass(frozen=True)
class DailyReportApiConfig:
    enabled: bool
    host: str
    port: int
    token: str


def load_daily_report_config() -> DailyReportConfig:
    enabled = os.getenv("DAILY_ATTENDANCE_REPORT_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        hour = int(os.getenv("DAILY_ATTENDANCE_REPORT_HOUR") or "23")
    except ValueError:
        hour = 23
    try:
        minute = int(os.getenv("DAILY_ATTENDANCE_REPORT_MINUTE") or "0")
    except ValueError:
        minute = 0
    hour = max(0, min(hour, 23))
    minute = max(0, min(minute, 59))

    tz = (os.getenv("DAILY_ATTENDANCE_REPORT_TIMEZONE") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    username = (os.getenv("DAILY_ATTENDANCE_REPORT_NOTIFY_USERNAME") or "benrenxing").strip().lstrip("@")

    tg_id_raw = (os.getenv("DAILY_ATTENDANCE_REPORT_NOTIFY_TG_ID") or "").strip()
    notify_tg_id: int | None = None
    if tg_id_raw:
        try:
            notify_tg_id = int(tg_id_raw)
        except ValueError:
            notify_tg_id = None

    return DailyReportConfig(
        enabled=enabled,
        report_hour=hour,
        report_minute=minute,
        timezone_name=tz,
        notify_tg_id=notify_tg_id,
        notify_username=username,
    )


def load_daily_report_api_config() -> DailyReportApiConfig:
    enabled = os.getenv("DAILY_ATTENDANCE_REPORT_API_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    host = (os.getenv("DAILY_ATTENDANCE_REPORT_API_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.getenv("DAILY_ATTENDANCE_REPORT_API_PORT") or "8787")
    except ValueError:
        port = 8787
    port = max(1, min(port, 65535))
    token = (os.getenv("DAILY_ATTENDANCE_REPORT_API_TOKEN") or "").strip()
    return DailyReportApiConfig(enabled=enabled, host=host, port=port, token=token)
