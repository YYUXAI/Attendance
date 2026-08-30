"""T 群：底部键盘仅离岗/返岗；T/QDYYZ 按 @用户名认人。T 群离岗超时 30 分钟。"""
from __future__ import annotations

_LEAVE_RETURN_KEYBOARD_ONLY_CHAT_IDS: frozenset[int] = frozenset(
    {
        -1002176838761,  # T-上班报备群
    }
)
_LEAVE_RETURN_KEYBOARD_ONLY_TITLES: frozenset[str] = frozenset(
    {
        "T-上班报备群",
    }
)

# 按 @username 认人（可不绑 tg_id）；含 T 群 + QDYYZ
_USERNAME_IDENTITY_CHAT_IDS: frozenset[int] = frozenset(
    {
        -1002176838761,  # T-上班报备群
        -1004373351741,  # QDYYZ 打卡报备群
    }
)
_USERNAME_IDENTITY_TITLES: frozenset[str] = frozenset(
    {
        "T-上班报备群",
        "QDYYZ 打卡报备群",
    }
)

# 默认与 YYMG 一致；仅 T 群 30 分钟
_DEFAULT_LEAVE_OVERTIME_MINUTES = 21
_T_GROUP_LEAVE_OVERTIME_MINUTES = 30
_T_GROUP_CHAT_IDS: frozenset[int] = frozenset({-1002176838761})
_T_GROUP_TITLES: frozenset[str] = frozenset({"T-上班报备群"})

# QDYYZ：管理员双导出 + OCR.space 打卡
_QDYYZ_CHAT_IDS: frozenset[int] = frozenset({-1004373351741})
_QDYYZ_TITLES: frozenset[str] = frozenset({"QDYYZ 打卡报备群"})


def is_qdyyz_chat(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    if chat_id is not None and int(chat_id) in _QDYYZ_CHAT_IDS:
        return True
    title = (chat_title or "").strip()
    return bool(title and title in _QDYYZ_TITLES)


def is_leave_return_keyboard_only_chat(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    if chat_id is not None and int(chat_id) in _LEAVE_RETURN_KEYBOARD_ONLY_CHAT_IDS:
        return True
    title = (chat_title or "").strip()
    return bool(title and title in _LEAVE_RETURN_KEYBOARD_ONLY_TITLES)


def is_username_identity_chat(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    """本群用 Telegram @用户名当名单唯一键，不要求私聊绑定 tg_id。"""
    if chat_id is not None and int(chat_id) in _USERNAME_IDENTITY_CHAT_IDS:
        return True
    title = (chat_title or "").strip()
    return bool(title and title in _USERNAME_IDENTITY_TITLES)


def normalize_tg_username(value: str | None) -> str:
    return (value or "").strip().lstrip("@").lower()


def leave_overtime_minutes_for_chat(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> int:
    if chat_id is not None and int(chat_id) in _T_GROUP_CHAT_IDS:
        return _T_GROUP_LEAVE_OVERTIME_MINUTES
    title = (chat_title or "").strip()
    if title and title in _T_GROUP_TITLES:
        return _T_GROUP_LEAVE_OVERTIME_MINUTES
    return _DEFAULT_LEAVE_OVERTIME_MINUTES
