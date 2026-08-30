from types import SimpleNamespace

from infra.checkin_ocrspace_config import is_ocrspace_extract_chat
from infra.leave_return_keyboard_only_config import (
    is_leave_return_keyboard_only_chat,
    is_qdyyz_chat,
    is_username_identity_chat,
    leave_overtime_minutes_for_chat,
)
from gateway_provider import checkin_module, event_module


class _FakeCursor:
    pass


def test_qdyyz_username_identity_falls_back_to_bound_tg_id(monkeypatch) -> None:
    """私聊已绑定 tg_id、但账号无 @username 时，QDYYZ 仍应能认人。"""
    chat_id = -1004373351741
    bound = SimpleNamespace(
        id=97,
        employee_id="70557",
        tg_id=8984258370,
        english_name="Tiekenfas",
        tg_username=None,
        registered_chat_id=8984258370,
    )

    def _no_username(cur, *, tg_username: str):
        return None

    def _by_tg_id(cur, *, tg_id: int):
        assert tg_id == 8984258370
        return bound

    monkeypatch.setattr(
        event_module.registrations_repo,
        "get_by_tg_username_cur",
        _no_username,
    )
    monkeypatch.setattr(
        event_module.registrations_repo,
        "get_by_tg_id_cur",
        _by_tg_id,
    )
    monkeypatch.setattr(
        checkin_module.registrations_repo,
        "get_by_tg_username_cur",
        _no_username,
    )
    monkeypatch.setattr(
        checkin_module.registrations_repo,
        "get_by_tg_id_cur",
        _by_tg_id,
    )

    reg, miss = event_module._registration_for_group_action(
        _FakeCursor(),
        tg_id=8984258370,
        tg_username=None,
        chat_id=chat_id,
        chat_title="QDYYZ 打卡报备群",
    )
    assert miss is None
    assert reg is bound

    reg2, miss2 = checkin_module._registration_for_checkin(
        _FakeCursor(),
        tg_id=8984258370,
        tg_username=None,
        chat_id=chat_id,
        chat_title="QDYYZ 打卡报备群",
    )
    assert miss2 is None
    assert reg2 is bound


def test_qdyyz_has_checkin_keyboard_username_identity_and_ocrspace() -> None:
    chat_id = -1004373351741
    title = "QDYYZ 打卡报备群"
    assert is_qdyyz_chat(chat_id=chat_id, chat_title=title)
    assert is_username_identity_chat(chat_id=chat_id, chat_title=title)
    assert is_username_identity_chat(chat_id=chat_id, chat_title=None)
    assert is_username_identity_chat(chat_id=None, chat_title=title)
    assert not is_leave_return_keyboard_only_chat(chat_id=chat_id, chat_title=title)
    assert is_ocrspace_extract_chat(chat_id=chat_id, chat_title=title)
    assert leave_overtime_minutes_for_chat(chat_id=chat_id, chat_title=title) == 21


def test_t_group_remains_keyboard_only_and_username_identity() -> None:
    chat_id = -1002176838761
    title = "T-上班报备群"
    assert is_username_identity_chat(chat_id=chat_id, chat_title=title)
    assert is_leave_return_keyboard_only_chat(chat_id=chat_id, chat_title=title)
    assert not is_ocrspace_extract_chat(chat_id=chat_id, chat_title=title)
    assert leave_overtime_minutes_for_chat(chat_id=chat_id, chat_title=title) == 30
