from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from infra.attendance_group_policy import title_has_capability
from infra.leave_return_keyboard_only_config import leave_overtime_minutes_for_chat
from repositories import temporary_leave_records_repo

# YYMG 返岗模板：离岗时长 >= 21 分钟时追加「提示：你已超时」
LEAVE_BACK_OVERTIME_MINUTES = 21


@dataclass(frozen=True)
class OpenLeaveDraftInfo:
    duration_text: str
    overtime: bool


def requires_leave_mutual_exclusion(
    *, chat_id: int, chat_title: str | None = None
) -> bool:
    del chat_id
    return title_has_capability(chat_title, "leave-mutual-exclusion")


def requires_leave_back_copy_fallback(
    *, chat_id: int, chat_title: str | None = None
) -> bool:
    del chat_id
    return title_has_capability(chat_title, "leave-back-copy-fallback")


def format_leave_duration_minutes(mins: int) -> str:
    if mins < 60:
        return f"{mins}分钟"
    hours, rem = divmod(int(mins), 60)
    if rem:
        return f"{hours}小时{rem}分钟"
    return f"{hours}小时"


def compute_open_leave_draft_info(
    *,
    employee_id: str,
    chat_id: int,
    chat_title: str | None = None,
    now_utc: datetime | None = None,
) -> OpenLeaveDraftInfo | None:
    """未返岗记录的离岗时长（用于返岗模板预填）。"""
    open_rec = temporary_leave_records_repo.get_latest_open(
        employee_id=str(employee_id),
        chat_id=int(chat_id),
    )
    if not open_rec:
        return None
    leave_at = open_rec.leave_at
    if not isinstance(leave_at, datetime):
        return None
    if leave_at.tzinfo is None:
        leave_at = leave_at.replace(tzinfo=timezone.utc)
    ref = now_utc or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    mins = max(0, int((ref - leave_at).total_seconds() // 60))
    threshold = leave_overtime_minutes_for_chat(
        chat_id=chat_id,
        chat_title=chat_title,
    )
    return OpenLeaveDraftInfo(
        duration_text=format_leave_duration_minutes(mins),
        overtime=mins >= threshold,
    )


def compute_open_leave_duration(
    *,
    employee_id: str,
    chat_id: int,
    now_utc: datetime | None = None,
) -> str | None:
    info = compute_open_leave_draft_info(
        employee_id=employee_id,
        chat_id=chat_id,
        now_utc=now_utc,
    )
    return info.duration_text if info else None


def check_can_leave(
    *, employee_id: str, chat_id: int, chat_title: str | None = None
) -> tuple[bool, str | None]:
    if not requires_leave_mutual_exclusion(
        chat_id=int(chat_id), chat_title=chat_title
    ):
        return True, None
    open_rec = temporary_leave_records_repo.get_latest_open(
        employee_id=str(employee_id),
        chat_id=int(chat_id),
    )
    if open_rec:
        return False, "您已离岗"
    return True, None


def check_can_back(
    *, employee_id: str, chat_id: int, chat_title: str | None = None
) -> tuple[bool, str | None]:
    if not requires_leave_mutual_exclusion(
        chat_id=int(chat_id), chat_title=chat_title
    ):
        return True, None
    open_rec = temporary_leave_records_repo.get_latest_open(
        employee_id=str(employee_id),
        chat_id=int(chat_id),
    )
    if not open_rec:
        return False, "您还未点击离岗"
    return True, None
