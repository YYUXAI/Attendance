"""Telegram 群「测试群」专属：班表来源 + 打卡后回写 Google 表。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 默认不携带真实 chat_id；启用时必须通过 TEST_GROUP_CHAT_IDS 配置。
_DEFAULT_TEST_GROUP_CHAT_IDS: frozenset[int] = frozenset()
_DEFAULT_TEST_GROUP_TITLES: frozenset[str] = frozenset({"测试群"})
# 测试群班表来源（Google Sheets）
_DEFAULT_TEST_GROUP_SHIFT_SPREADSHEET_ID = "1Q0O84cg26gkLU8uJXwOYaHBRRD07FQGYs7Ept-Jfw90"
_DEFAULT_TEST_GROUP_SHIFT_SHEET_GID = 0
_DEFAULT_TEST_GROUP_ATTENDANCE_SHEET_TITLE = "工作表1"


@dataclass(frozen=True)
class TestGroupGoogleConfig:
    enabled: bool
    chat_ids: frozenset[int]
    group_titles: frozenset[str]
    shift_spreadsheet_id: str
    shift_sheet_gid: int | None
    attendance_spreadsheet_id: str
    attendance_sheet_gid: int | None
    attendance_sheet_title: str
    credentials_json: str
    timezone: str


def _parse_int_set(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return frozenset(out)


def _parse_str_set(raw: str) -> frozenset[str]:
    out: set[str] = set()
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if p:
            out.add(p)
    return frozenset(out)


def load_test_group_google_config() -> TestGroupGoogleConfig:
    enabled = os.getenv("TEST_GROUP_GOOGLE_SHEETS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    chat_ids = _parse_int_set(os.getenv("TEST_GROUP_CHAT_IDS") or "")
    if not chat_ids:
        chat_ids = _DEFAULT_TEST_GROUP_CHAT_IDS
    titles = _parse_str_set(os.getenv("TEST_GROUP_GROUP_TITLES") or "")
    if not titles:
        titles = _DEFAULT_TEST_GROUP_TITLES
    shift_sid = (
        os.getenv("TEST_GROUP_SHIFT_SPREADSHEET_ID") or _DEFAULT_TEST_GROUP_SHIFT_SPREADSHEET_ID
    ).strip()
    att_sid = (os.getenv("TEST_GROUP_ATTENDANCE_SPREADSHEET_ID") or "").strip()
    att_title = (
        os.getenv("TEST_GROUP_ATTENDANCE_SHEET_TITLE") or _DEFAULT_TEST_GROUP_ATTENDANCE_SHEET_TITLE
    ).strip()
    shift_gid_raw = (
        os.getenv("TEST_GROUP_SHIFT_SHEET_GID") or str(_DEFAULT_TEST_GROUP_SHIFT_SHEET_GID)
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
        or "secrets/google_service_account.json"
    ).strip()
    if creds and not os.path.isabs(creds):
        root = Path(__file__).resolve().parents[1]
        creds = str((root / creds).resolve())
    tz = (os.getenv("TEST_GROUP_GOOGLE_SHEETS_TIMEZONE") or "Asia/Shanghai").strip()
    return TestGroupGoogleConfig(
        enabled=enabled,
        chat_ids=chat_ids,
        group_titles=titles,
        shift_spreadsheet_id=shift_sid,
        shift_sheet_gid=_gid(shift_gid_raw),
        attendance_spreadsheet_id=att_sid,
        attendance_sheet_gid=_gid(att_gid_raw),
        attendance_sheet_title=att_title or _DEFAULT_TEST_GROUP_ATTENDANCE_SHEET_TITLE,
        credentials_json=creds,
        timezone=tz or "Asia/Shanghai",
    )


def primary_test_group_chat_id() -> int:
    """Google 考勤回写固定统计此群的打卡记录（测试群，非 New-考勤测试群）。"""
    cfg = load_test_group_google_config()
    if cfg.chat_ids:
        return min(cfg.chat_ids)
    raise RuntimeError("TEST_GROUP_CHAT_IDS is required when test group Google sync is enabled.")


def is_test_group_chat(*, chat_id: int | None, chat_title: str | None = None) -> bool:
    cfg = load_test_group_google_config()
    if chat_id is not None and int(chat_id) in cfg.chat_ids:
        return True
    title = (chat_title or "").strip()
    return bool(title and title in cfg.group_titles)


def test_group_uses_slack_name_time_date_checkin() -> bool:
    """测试群专规：TIME.IS + Slack 浮窗，校验姓名/时间/日期（非工号远程打卡）。"""
    return os.getenv("TEST_GROUP_SLACK_CHECKIN", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
