"""远程工号打卡：桌面工号文件夹 + 北京时间，配文仅校验工号。"""
from __future__ import annotations

from infra.attendance_group_policy import title_has_capability
from repositories import attendance_runtime_config_repo


def is_yymg_attendance_summary_chat(*, chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    return attendance_runtime_config_repo.active_chat_has_capability(
        chat_id=chat_id,
        capability="remote-diff-checkin",
    )


def yymg_summary_excluded_employee_ids() -> frozenset[str]:
    return attendance_runtime_config_repo.business_fact_set(
        fact_kind="remote_diff_summary_excluded_employee"
    )


def requires_remote_diff_checkin(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    del chat_id
    return title_has_capability(chat_title, "remote-diff-checkin")
