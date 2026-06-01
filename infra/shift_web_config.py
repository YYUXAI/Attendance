from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ShiftWebConfig:
    enabled: bool
    public_base_url: str
    timezone_name: str
    browser_dev: bool


def load_shift_web_config() -> ShiftWebConfig:
    enabled = os.getenv("SHIFT_WEB_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    public_base_url = (os.getenv("SHIFT_WEB_APP_PUBLIC_URL") or "").strip().rstrip("/")
    tz = (os.getenv("SHIFT_WEB_TIMEZONE") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    browser_dev = os.getenv("SHIFT_WEB_BROWSER_DEV", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return ShiftWebConfig(
        enabled=enabled,
        public_base_url=public_base_url,
        timezone_name=tz,
        browser_dev=browser_dev,
    )


def current_year_month(*, tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m")


def build_shift_web_app_url(
    *,
    year_month: str | None = None,
    web_session: str | None = None,
) -> str | None:
    cfg = load_shift_web_config()
    if not cfg.enabled or not cfg.public_base_url:
        return None
    ym = year_month or current_year_month(tz_name=cfg.timezone_name)
    url = f"{cfg.public_base_url}/shift-app/index.html?year_month={ym}"
    if web_session:
        from urllib.parse import urlencode

        url = f"{url}&{urlencode({'web_session': web_session})}"
    return url


def build_checkin_web_app_url(*, web_session: str) -> str | None:
    cfg = load_shift_web_config()
    if not cfg.enabled or not cfg.public_base_url:
        return None
    from urllib.parse import urlencode

    return f"{cfg.public_base_url}/checkin-app/index.html?{urlencode({'web_session': web_session})}"
