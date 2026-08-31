"""Y-UX-KQBBQ：打卡校验姓名 + 北京时间时刻 + 日期。"""
from __future__ import annotations

_KQBBQ_CHAT_IDS: frozenset[int] = frozenset({-1003883297177})
_KQBBQ_TITLES: frozenset[str] = frozenset({"Y-UX-KQBBQ"})


def is_kqbbq_chat(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    if chat_id is not None and int(chat_id) in _KQBBQ_CHAT_IDS:
        return True
    title = (chat_title or "").strip()
    return bool(title and title in _KQBBQ_TITLES)
