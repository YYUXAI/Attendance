"""工号打卡群：不再回写 Google 考勤表（考勤回写仅测试群，见 test_group_google_config）。"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteDiffGoogleSheetsConfig:
    enabled: bool
    spreadsheet_id: str
    sheet_gid: int | None
    credentials_json: str
    timezone: str


def load_remote_diff_google_sheets_config() -> RemoteDiffGoogleSheetsConfig:
    enabled = os.getenv("REMOTE_DIFF_GOOGLE_SHEETS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    spreadsheet_id = (os.getenv("REMOTE_DIFF_GOOGLE_SHEETS_SPREADSHEET_ID") or "").strip()
    gid_raw = (os.getenv("REMOTE_DIFF_GOOGLE_SHEETS_SHEET_GID") or "").strip()
    sheet_gid: int | None = None
    if gid_raw:
        try:
            sheet_gid = int(gid_raw)
        except ValueError:
            sheet_gid = None
    creds = (
        os.getenv("REMOTE_DIFF_GOOGLE_SHEETS_CREDENTIALS_JSON")
        or os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
        or ""
    ).strip()
    tz = (os.getenv("REMOTE_DIFF_GOOGLE_SHEETS_TIMEZONE") or "Asia/Shanghai").strip()
    return RemoteDiffGoogleSheetsConfig(
        enabled=enabled,
        spreadsheet_id=spreadsheet_id,
        sheet_gid=sheet_gid,
        credentials_json=creds,
        timezone=tz or "Asia/Shanghai",
    )
