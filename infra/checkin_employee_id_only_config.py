"""可选：标准 time.is 打卡仅校验工号（无文件夹）。工号打卡群请用 remote_diff。"""
from __future__ import annotations

from infra.attendance_group_policy import title_has_capability


def requires_employee_id_only_checkin(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    del chat_id
    return title_has_capability(chat_title, "employee-id-only-checkin")
