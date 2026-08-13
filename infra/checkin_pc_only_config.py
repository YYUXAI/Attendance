"""仅指定考勤群要求 PC 端截图（手机端浏览器 / Telegram 拒绝打卡）。"""
from __future__ import annotations

from infra.attendance_group_policy import title_has_capability


def requires_pc_screenshot(
    *, chat_id: int | None, chat_title: str | None = None
) -> bool:
    del chat_id
    return title_has_capability(chat_title, "pc-only-screenshot")
