"""UX 助手考勤测试群：AI 识图试跑（不入库）与测试群打卡文案。"""
from __future__ import annotations

_DEFAULT_CHAT_IDS: frozenset[int] = frozenset(
    {
        -1004347063533,  # ux助手考勤测试群
    }
)
_DEFAULT_TITLES: frozenset[str] = frozenset(
    {
        "ux助手考勤测试群",
    }
)


def is_ux_assistant_attendance_test_group(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    if chat_id is not None and int(chat_id) in _DEFAULT_CHAT_IDS:
        return True
    title = (chat_title or "").strip()
    return bool(title and title in _DEFAULT_TITLES)
