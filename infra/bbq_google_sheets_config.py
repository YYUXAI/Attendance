"""BBQ 群（Y-UX-KQBBQ）打卡记录同步到 Google 表。"""
from __future__ import annotations

import os
from dataclasses import dataclass

from infra.attendance_group_policy import title_has_capability
from repositories import attendance_runtime_config_repo


@dataclass(frozen=True)
class BbqGoogleSheetsConfig:
    enabled: bool
    spreadsheet_id: str
    sheet_title: str
    credentials_json: str
    timezone: str


def load_bbq_google_sheets_config() -> BbqGoogleSheetsConfig:
    enabled = (os.getenv("BBQ_GOOGLE_SHEETS_ENABLED") or "false").strip().lower() == "true"
    spreadsheet_id = (os.getenv("BBQ_GOOGLE_SHEETS_SPREADSHEET_ID") or "").strip()
    sheet_title = (os.getenv("BBQ_GOOGLE_SHEETS_SHEET_TITLE") or "").strip()

    creds = (
        os.getenv("BBQ_GOOGLE_SHEETS_CREDENTIALS_JSON")
        or os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
        or ""
    ).strip()
    tz = (os.getenv("BBQ_GOOGLE_SHEETS_TIMEZONE") or "Asia/Shanghai").strip()
    return BbqGoogleSheetsConfig(
        enabled=enabled,
        spreadsheet_id=spreadsheet_id,
        sheet_title=sheet_title,
        credentials_json=creds,
        timezone=tz or "Asia/Shanghai",
    )


def is_bbq_chat(*, chat_id: int | None, chat_title: str | None = None) -> bool:
    del chat_id
    return title_has_capability(chat_title, "bbq-google-sheets")


def is_bbq_attendance_summary_chat(
    *, chat_id: int | None, chat_title: str | None = None
) -> bool:
    if chat_title is not None:
        return title_has_capability(chat_title, "bbq-google-sheets")
    if chat_id is None:
        return False
    return attendance_runtime_config_repo.active_chat_has_capability(
        chat_id=chat_id,
        capability="bbq-google-sheets",
    )


def bbq_summary_excluded_employee_ids() -> frozenset[str]:
    return attendance_runtime_config_repo.business_fact_set(
        fact_kind="bbq_summary_excluded_employee"
    )
