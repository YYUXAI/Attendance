from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardRemove

from handlers import attendance_actions, menu
from handlers.register import RegisterBeginInputFilter
from keyboards import actions_menu
from keyboards.actions_menu import reply_actions_menu
from keyboards.main_menu import build_private_actions_inline


def test_private_actions_inline_preserves_attendance_actions() -> None:
    markup = build_private_actions_inline(
        is_admin=True,
        shift_web_app_url="https://attendance.example.test/shift",
    )

    assert [[button.text for button in row] for row in markup.inline_keyboard] == [
        ["注册", "个人"],
        ["导出", "班表"],
    ]
    assert markup.inline_keyboard[0][0].callback_data == "reg:begin"
    assert markup.inline_keyboard[0][1].callback_data == "profile:myinfo"
    assert markup.inline_keyboard[1][0].callback_data == "act:export"


def test_shift_menu_url_never_puts_a_session_credential_in_query(monkeypatch) -> None:
    monkeypatch.setenv("SHIFT_WEB_ENABLED", "true")
    monkeypatch.setenv("SHIFT_WEB_APP_PUBLIC_URL", "https://attendance.example.test")

    url = actions_menu.build_shift_web_app_url_for_admin(tg_id=42)

    assert url is not None
    assert "year_month=" in url
    assert "web_session=" not in url


def test_private_actions_menu_removes_reply_keyboard_then_sends_inline_menu() -> None:
    class IncomingMessage:
        chat = SimpleNamespace(type="private")
        from_user = None

        def __init__(self) -> None:
            self.replies: list[tuple[str, object]] = []

        async def reply(self, text: str, *, reply_markup):
            self.replies.append((text, reply_markup))

    message = IncomingMessage()
    asyncio.run(reply_actions_menu(
        message=message,
        is_admin=False,
        tg_id=42,
    ))

    assert len(message.replies) == 2
    assert message.replies[0][0] == actions_menu.PRIVATE_REPLY_KEYBOARD_REMOVAL_TEXT
    assert isinstance(message.replies[0][1], ReplyKeyboardRemove)
    assert message.replies[1][0] == actions_menu.MENU_TEXT
    assert isinstance(message.replies[1][1], InlineKeyboardMarkup)
    assert [button.text for button in message.replies[1][1].inline_keyboard[0]] == ["注册", "个人"]


def test_group_actions_menu_keeps_original_reply_keyboard(monkeypatch) -> None:
    group_markup = object()
    monkeypatch.setattr(actions_menu, "is_omni_group_chat", lambda chat_id: False)
    monkeypatch.setattr(actions_menu, "build_group_reply_keyboard", lambda: group_markup)

    class GroupMessage:
        chat = SimpleNamespace(type="supergroup", id=-1001)
        from_user = SimpleNamespace(id=42)

        def __init__(self) -> None:
            self.replies: list[tuple[str, object]] = []

        async def reply(self, text: str, *, reply_markup):
            self.replies.append((text, reply_markup))

    message = GroupMessage()
    asyncio.run(reply_actions_menu(
        message=message,
        is_admin=False,
        tg_id=42,
    ))

    assert message.replies == [(actions_menu.GROUP_REPLY_MENU_TEXT, group_markup)]


def test_register_begin_filter_accepts_unified_binding_alias() -> None:
    filter_ = RegisterBeginInputFilter()

    async def matches(text: str) -> bool:
        return await filter_(SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            text=text,
        ))

    assert asyncio.run(matches("注册"))
    assert asyncio.run(matches("绑定考勤资料"))
    assert asyncio.run(matches("/attendance_register"))
    assert not asyncio.run(matches("个人"))


def test_unified_menu_callback_reuses_actions_menu(monkeypatch) -> None:
    send_actions_menu = AsyncMock()
    monkeypatch.setattr(menu, "_send_actions_menu", send_actions_menu)
    actor = SimpleNamespace(id=42)
    message = SimpleNamespace(chat=SimpleNamespace(type="private"))
    callback = SimpleNamespace(
        answer=AsyncMock(),
        message=message,
        from_user=actor,
    )

    asyncio.run(menu.unified_attendance_menu_callback(callback))

    callback.answer.assert_awaited_once_with()
    send_actions_menu.assert_awaited_once_with(message, user=actor)


def test_attendance_command_reuses_actions_menu(monkeypatch) -> None:
    send_actions_menu = AsyncMock()
    monkeypatch.setattr(menu, "_send_actions_menu", send_actions_menu)
    message = SimpleNamespace(chat=SimpleNamespace(type="private"))

    asyncio.run(menu.attendance_menu_command(message))

    send_actions_menu.assert_awaited_once_with(message)


def test_actions_menu_clears_registration_input_state(monkeypatch) -> None:
    cleared: list[tuple[str, int]] = []
    reply_menu = AsyncMock()
    monkeypatch.setenv("ATTENDANCE_BOT_OWNER", "ux_assistant")
    monkeypatch.setattr(
        menu.register_service,
        "clear_waiting_register_input",
        lambda *, bot_owner, tg_id: cleared.append((bot_owner, tg_id)),
    )
    monkeypatch.setattr(menu, "is_admin_by_tg_id", lambda *, tg_id: False)
    monkeypatch.setattr(menu, "reply_actions_menu", reply_menu)
    actor = SimpleNamespace(id=42)
    message = SimpleNamespace(chat=SimpleNamespace(type="private"), from_user=actor)

    asyncio.run(menu._send_actions_menu(message))

    assert cleared == [("ux_assistant", 42)]
    reply_menu.assert_awaited_once_with(
        message=message,
        is_admin=False,
        tg_id=42,
    )


def test_non_admin_does_not_see_admin_actions() -> None:
    markup = build_private_actions_inline(
        is_admin=False,
        shift_web_app_url="https://attendance.example.test/shift",
    )

    assert [[button.text for button in row] for row in markup.inline_keyboard] == [
        ["注册", "个人"],
    ]


def test_attendance_admin_sees_existing_admin_actions() -> None:
    markup = build_private_actions_inline(
        is_admin=True,
        shift_web_app_url="https://attendance.example.test/shift",
    )

    assert [[button.text for button in row] for row in markup.inline_keyboard] == [
        ["注册", "个人"],
        ["导出", "班表"],
    ]


@pytest.mark.parametrize(
    ("is_omni_superadmin", "is_attendance_admin", "expected_admin_menu"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, True),
        (True, True, True),
    ],
)
def test_omni_superadmin_and_attendance_admin_never_grant_each_other(
    monkeypatch,
    is_omni_superadmin: bool,
    is_attendance_admin: bool,
    expected_admin_menu: bool,
) -> None:
    actor_id = 42
    monkeypatch.setenv(
        "TELEGRAM_SUPERADMIN_USER_IDS",
        str(actor_id) if is_omni_superadmin else "",
    )
    monkeypatch.setattr(menu, "is_admin_by_tg_id", lambda *, tg_id: is_attendance_admin)
    monkeypatch.setattr(menu.register_service, "clear_waiting_register_input", lambda **_: None)
    reply_menu = AsyncMock()
    monkeypatch.setattr(menu, "reply_actions_menu", reply_menu)
    message = SimpleNamespace(
        chat=SimpleNamespace(type="private"),
        from_user=SimpleNamespace(id=actor_id),
    )

    asyncio.run(menu._send_actions_menu(message))

    reply_menu.assert_awaited_once_with(
        message=message,
        is_admin=expected_admin_menu,
        tg_id=actor_id,
    )


def test_legacy_admin_menu_texts_end_registration_session(monkeypatch) -> None:
    cleared: list[tuple[str, int]] = []
    monkeypatch.setenv("ATTENDANCE_BOT_OWNER", "ux_assistant")
    monkeypatch.setattr(
        attendance_actions.register_service,
        "clear_waiting_register_input",
        lambda *, bot_owner, tg_id: cleared.append((bot_owner, tg_id)),
    )
    open_shift = AsyncMock()
    prompt_export = AsyncMock()
    monkeypatch.setattr(attendance_actions, "_open_shift_web_app", open_shift)
    monkeypatch.setattr(attendance_actions, "_prompt_export_range", prompt_export)
    message = SimpleNamespace(
        chat=SimpleNamespace(type="private"),
        from_user=SimpleNamespace(id=42),
    )

    asyncio.run(attendance_actions.open_shift_web_app_message(message))
    asyncio.run(attendance_actions.export_today_message(message))

    assert cleared == [("ux_assistant", 42), ("ux_assistant", 42)]
    open_shift.assert_awaited_once_with(message=message, tg_id=42)
    prompt_export.assert_awaited_once_with(message=message, tg_id=42)
