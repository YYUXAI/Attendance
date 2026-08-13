"""Telegram 群「测试群」专属：班表来源 + 打卡后回写 Google 表。"""
from __future__ import annotations

import os
from dataclasses import dataclass

from infra.attendance_group_policy import title_has_capability


@dataclass(frozen=True)
class ConfiguredTestGroupGoogleConfig:
    enabled: bool
    shift_spreadsheet_id: str
    shift_sheet_gid: int | None
    attendance_spreadsheet_id: str
    attendance_sheet_gid: int | None
    attendance_sheet_title: str
    credentials_json: str
    timezone: str


def load_test_group_google_config() -> ConfiguredTestGroupGoogleConfig:
    enabled = os.getenv("TEST_GROUP_GOOGLE_SHEETS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    shift_sid = (os.getenv("TEST_GROUP_SHIFT_SPREADSHEET_ID") or "").strip()
    att_sid = (os.getenv("TEST_GROUP_ATTENDANCE_SPREADSHEET_ID") or "").strip()
    att_title = (os.getenv("TEST_GROUP_ATTENDANCE_SHEET_TITLE") or "").strip()
    shift_gid_raw = (
        os.getenv("TEST_GROUP_SHIFT_SHEET_GID") or "0"
    ).strip()
    att_gid_raw = (os.getenv("TEST_GROUP_ATTENDANCE_SHEET_GID") or "0").strip()

    def _gid(raw: str) -> int | None:
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    creds = (
        os.getenv("TEST_GROUP_GOOGLE_SHEETS_CREDENTIALS_JSON")
        or os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
        or ""
    ).strip()
    tz = (os.getenv("TEST_GROUP_GOOGLE_SHEETS_TIMEZONE") or "Asia/Shanghai").strip()
    return ConfiguredTestGroupGoogleConfig(
        enabled=enabled,
        shift_spreadsheet_id=shift_sid,
        shift_sheet_gid=_gid(shift_gid_raw),
        attendance_spreadsheet_id=att_sid,
        attendance_sheet_gid=_gid(att_gid_raw),
        attendance_sheet_title=att_title,
        credentials_json=creds,
        timezone=tz or "Asia/Shanghai",
    )


def is_test_group_chat(*, chat_id: int | None, chat_title: str | None = None) -> bool:
    del chat_id
    return title_has_capability(chat_title, "test-group-google-sheets")


def configured_test_group_uses_slack_name_time_date_checkin() -> bool:
    """测试群专规：TIME.IS + Slack 浮窗，校验姓名/时间/日期（非工号远程打卡）。"""
    return os.getenv("TEST_GROUP_SLACK_CHECKIN", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
