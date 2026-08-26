from infra.leave_return_keyboard_only_config import (
    is_leave_return_keyboard_only_chat,
    is_username_identity_chat,
    leave_overtime_minutes_for_chat,
)


def test_qdyyz_is_username_identity_but_not_keyboard_only() -> None:
    chat_id = -1004373351741
    title = "QDYYZ 打卡报备群"
    assert is_username_identity_chat(chat_id=chat_id, chat_title=title)
    assert is_username_identity_chat(chat_id=chat_id, chat_title=None)
    assert is_username_identity_chat(chat_id=None, chat_title=title)
    assert not is_leave_return_keyboard_only_chat(chat_id=chat_id, chat_title=title)
    assert leave_overtime_minutes_for_chat(chat_id=chat_id, chat_title=title) == 21


def test_t_group_remains_keyboard_only_and_username_identity() -> None:
    chat_id = -1002176838761
    title = "T-上班报备群"
    assert is_username_identity_chat(chat_id=chat_id, chat_title=title)
    assert is_leave_return_keyboard_only_chat(chat_id=chat_id, chat_title=title)
    assert leave_overtime_minutes_for_chat(chat_id=chat_id, chat_title=title) == 30
