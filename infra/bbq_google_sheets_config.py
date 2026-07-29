"""BBQ 群（Y-UX-KQBBQ）打卡记录同步到 Google 表。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from infra.test_group_google_config import load_test_group_google_config

DEFAULT_BBQ_CHAT_ID = -1003883297177
DEFAULT_BBQ_SHEET_TITLE = "Y-UX-KQBBQ打卡记录"
# Y-UX-KQBBQ：开班/今日概览/群统计不再计入的工号（可用 env 覆盖，逗号分隔；空字符串=不排除）
DEFAULT_BBQ_SUMMARY_EXCLUDE_EMPLOYEE_IDS = "74322"  # YILIAZA


@dataclass(frozen=True)
class BbqGoogleSheetsConfig:
    enabled: bool
    chat_id: int
    spreadsheet_id: str
    sheet_title: str
    credentials_json: str
    timezone: str


def load_bbq_google_sheets_config() -> BbqGoogleSheetsConfig:
    test_cfg = load_test_group_google_config()
    raw_enabled = (os.getenv("BBQ_GOOGLE_SHEETS_ENABLED") or "").strip().lower()
    if raw_enabled:
        enabled = raw_enabled in {"1", "true", "yes", "on"}
    else:
        enabled = test_cfg.enabled

    chat_raw = (os.getenv("BBQ_GOOGLE_SHEETS_CHAT_ID") or str(DEFAULT_BBQ_CHAT_ID)).strip()
    try:
        chat_id = int(chat_raw)
    except ValueError:
        chat_id = DEFAULT_BBQ_CHAT_ID

    spreadsheet_id = (
        os.getenv("BBQ_GOOGLE_SHEETS_SPREADSHEET_ID") or test_cfg.attendance_spreadsheet_id
    ).strip()
    sheet_title = (
        os.getenv("BBQ_GOOGLE_SHEETS_SHEET_TITLE") or DEFAULT_BBQ_SHEET_TITLE
    ).strip()

    creds = (
        os.getenv("BBQ_GOOGLE_SHEETS_CREDENTIALS_JSON")
        or test_cfg.credentials_json
        or "secrets/google_service_account.json"
    ).strip()
    if creds and not os.path.isabs(creds):
        root = Path(__file__).resolve().parents[1]
        creds = str((root / creds).resolve())

    tz = (os.getenv("BBQ_GOOGLE_SHEETS_TIMEZONE") or test_cfg.timezone or "Asia/Shanghai").strip()
    return BbqGoogleSheetsConfig(
        enabled=enabled,
        chat_id=chat_id,
        spreadsheet_id=spreadsheet_id,
        sheet_title=sheet_title or DEFAULT_BBQ_SHEET_TITLE,
        credentials_json=creds,
        timezone=tz or "Asia/Shanghai",
    )


def is_bbq_chat(*, chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    cfg = load_bbq_google_sheets_config()
    if not cfg.enabled:
        return False
    return int(chat_id) == int(cfg.chat_id)


def is_bbq_attendance_summary_chat(*, chat_id: int | None) -> bool:
    """Y-UX-KQBBQ 群：23:00 概览等展示规则（与 Google 表同步开关无关）。"""
    if chat_id is None:
        return False
    return int(chat_id) == DEFAULT_BBQ_CHAT_ID


def bbq_summary_excluded_employee_ids() -> frozenset[str]:
    """BBQ 群统计排除名单（开班、今日概览、按群导出同源）。"""
    raw = os.getenv("BBQ_SUMMARY_EXCLUDE_EMPLOYEE_IDS")
    if raw is None:
        raw = DEFAULT_BBQ_SUMMARY_EXCLUDE_EMPLOYEE_IDS
    return frozenset(x.strip() for x in str(raw).split(",") if x.strip())
