from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from repositories import admin_list_repo

log = logging.getLogger(__name__)

_NO_PERMISSION_TEXT = "你没有权限使用该指令"


def _format_utc_now(now_utc: datetime) -> str:
    return now_utc.strftime("%Y-%m-%d %H:%M:%S")


def build_test_command_reply(
    *,
    tg_id: int,
    tg_username: Optional[str],
    chat_id: int,
    attachment_file_id: Optional[str],
    now_utc: Optional[datetime] = None,
) -> str:
    """
    同步管理员 /test：校验权限并生成完整回复文案（含无权限提示）。
    """
    try:
        is_admin = admin_list_repo.is_admin_by_tg_id(tg_id=int(tg_id))
    except Exception:
        log.exception("admin_test: failed to check admin for tg_id=%s", tg_id)
        return "暂时无法校验权限，请稍后再试。"

    if not is_admin:
        return _NO_PERMISSION_TEXT

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    utc_str = _format_utc_now(now)

    uname = (tg_username or "").strip()
    if uname:
        username_line = f"@{uname}"
    else:
        username_line = "无"

    lines = [
        f"telegram_id：{int(tg_id)}",
        "",
        f"用户名：{username_line}",
        f"chat_id：{int(chat_id)}",
        f"utc_now：{utc_str}",
    ]
    if attachment_file_id:
        lines.append(f"file_id：{attachment_file_id}")
    return "\n".join(lines)
