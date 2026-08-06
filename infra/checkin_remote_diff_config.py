"""远程工号打卡：桌面工号文件夹 + 北京时间，配文仅校验工号。"""
from __future__ import annotations

import os

# YYMG-DKQ-(NEW) / 测试群 / New-考勤测试群（规则一致）
DEFAULT_YYMG_CHAT_ID = 0
_DEFAULT_REMOTE_DIFF_CHAT_IDS: tuple[int, ...] = ()
_DEFAULT_REMOTE_DIFF_GROUP_TITLES = (
    "YYMG-DKQ-(NEW)",
    "测试群",
    "New-考勤测试群",
)
# YYMG-DKQ-(NEW)：开班/今日概览/导出不再计入的工号（可用 env 覆盖，逗号分隔；空字符串=不排除）
DEFAULT_YYMG_SUMMARY_EXCLUDE_EMPLOYEE_IDS = "99999"


def remote_diff_group_titles() -> tuple[str, ...]:
    """
    兼容两种配置：
    - CHECKIN_REMOTE_DIFF_GROUP_TITLES: 逗号分隔多个群名
    - CHECKIN_REMOTE_DIFF_GROUP_TITLE: 旧版单群名配置
    """
    raw_multi = (os.getenv("CHECKIN_REMOTE_DIFF_GROUP_TITLES") or "").strip()
    if raw_multi:
        items = [x.strip() for x in raw_multi.replace("，", ",").split(",") if x.strip()]
        if items:
            return tuple(items)
    raw_single = (os.getenv("CHECKIN_REMOTE_DIFF_GROUP_TITLE") or "").strip()
    if raw_single:
        return (raw_single,)
    return _DEFAULT_REMOTE_DIFF_GROUP_TITLES


def remote_diff_chat_ids() -> frozenset[int]:
    raw = (os.getenv("CHECKIN_REMOTE_DIFF_CHAT_IDS") or "").strip()
    if not raw:
        return frozenset(_DEFAULT_REMOTE_DIFF_CHAT_IDS)
    out: set[int] = set()
    for part in raw.replace("，", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return frozenset(out)


def is_yymg_attendance_summary_chat(*, chat_id: int | None) -> bool:
    """YYMG-DKQ-(NEW) 群：开班/概览/导出统计排除规则。"""
    if chat_id is None:
        return False
    return DEFAULT_YYMG_CHAT_ID != 0 and int(chat_id) == DEFAULT_YYMG_CHAT_ID


def yymg_summary_excluded_employee_ids() -> frozenset[str]:
    """YYMG 群统计排除名单（开班、今日概览、按群/MGZ 导出同源）。"""
    raw = os.getenv("YYMG_SUMMARY_EXCLUDE_EMPLOYEE_IDS")
    if raw is None:
        raw = DEFAULT_YYMG_SUMMARY_EXCLUDE_EMPLOYEE_IDS
    return frozenset(x.strip() for x in str(raw).split(",") if x.strip())


def requires_remote_diff_checkin(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    """是否为远程差异识别群（与 CHECKIN_PC_ONLY 的考勤机器人测试群无关）。"""
    from infra.test_group_google_config import (
        is_test_group_chat,
        test_group_uses_slack_name_time_date_checkin,
    )

    if is_test_group_chat(chat_id=chat_id, chat_title=chat_title):
        if test_group_uses_slack_name_time_date_checkin():
            return False
    if chat_id is not None and int(chat_id) in remote_diff_chat_ids():
        return True
    title = (chat_title or "").strip()
    expected_titles = remote_diff_group_titles()
    return bool(title and expected_titles and title in expected_titles)
