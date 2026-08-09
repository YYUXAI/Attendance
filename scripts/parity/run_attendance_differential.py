from __future__ import annotations

import argparse
import asyncio
import base64
import importlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-root", type=Path)
    parser.add_argument("--mode", choices=("old", "current"))
    parser.add_argument("--import-root", type=Path)
    args = parser.parse_args()
    if args.mode:
        if args.import_root is None:
            raise SystemExit("--import-root is required with --mode")
        sys.path.insert(0, str(args.import_root.resolve()))
        trace = asyncio.run(old_trace() if args.mode == "old" else current_trace())
        print(json.dumps(trace, ensure_ascii=False, sort_keys=True))
        return
    if args.old_root is None:
        raise SystemExit("--old-root is required")

    script = Path(__file__).resolve()
    current_root = script.parents[2]
    old_python = args.old_root / ".venv/bin/python"
    current_python = current_root / ".venv/bin/python"
    old = run_trace(old_python, script, "old", args.old_root)
    current = run_trace(current_python, script, "current", current_root)
    if old != current:
        raise AssertionError(
            "Attendance old/current visible traces differ:\n"
            f"old={json.dumps(old, ensure_ascii=False, sort_keys=True)}\n"
            f"current={json.dumps(current, ensure_ascii=False, sort_keys=True)}"
        )
    print(json.dumps({
        "baseline": "Attendance@1b9c779",
        "scenarios": sorted(old),
        "scenarioIds": [
            "AT-ADMIN-EXPORT",
            "AT-GROUP-START",
            "AT-GROUP-UNKNOWN-IGNORED",
            "AT-PRIVATE-MENU-ADMIN",
            "AT-PRIVATE-MENU-USER",
        ],
        "result": "PASS",
    }, ensure_ascii=False, sort_keys=True))


def run_trace(
    python: Path,
    script: Path,
    mode: str,
    import_root: Path,
) -> dict[str, Any]:
    if not python.is_file():
        raise RuntimeError(f"Python runtime is missing for {mode} baseline")
    env = {
        **os.environ,
        "ATTENDANCE_BOT_OWNER": "ux_assistant",
        "SHIFT_WEB_ENABLED": "true",
        "SHIFT_WEB_APP_PUBLIC_URL": "https://attendance.example.test",
    }
    completed = subprocess.run(
        [
            str(python),
            str(script),
            "--mode",
            mode,
            "--import-root",
            str(import_root),
        ],
        cwd=import_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


async def old_trace() -> dict[str, Any]:
    from keyboards import actions_menu  # type: ignore[import-not-found]
    from handlers import attendance_actions, menu, profile, register  # type: ignore[import-not-found]

    actions_menu.is_omni_group_chat = lambda _chat_id: False
    register.registrations_repo.get_by_tg_id = lambda _tg_id: None
    register.register_service.mark_waiting_register_input = lambda **_kwargs: None

    class RegistrationMessage:
        chat = SimpleNamespace(type="private", id=87001)

        def __init__(self) -> None:
            self.replies: list[tuple[str, Any]] = []

        async def reply(self, text: str) -> None:
            self.replies.append((text, None))

    registration_message = RegistrationMessage()
    await register._begin_register_in_private(
        message=registration_message,
        tg_id=87001,
    )
    export_trace = await old_export_trace(attendance_actions)
    attendance_actions.build_shift_web_app_url_for_admin = (
        lambda *, tg_id: (
            "https://attendance.example.test/shift-app/index.html"
            "?year_month=2026-08"
        )
    )
    profile.profile_service.get_my_profile_by_tg_id = lambda **_kwargs: SimpleNamespace(
        message="你还未完成注册，请先注册后再查看我的信息。",
        ok=False,
        error_code="NOT_REGISTERED",
    )
    ignored_group_trace = await old_ignored_group_trace()

    async def session_menu_trace(text: str, *, is_admin: bool) -> dict[str, Any]:
        released: list[int] = []
        clear = lambda **kwargs: released.append(int(kwargs["tg_id"]))
        profile.register_service.clear_waiting_register_input = clear
        attendance_actions.register_service.clear_waiting_register_input = clear
        attendance_actions.admin_list_repo.is_admin_by_tg_id = (
            lambda *, tg_id: is_admin
        )
        message = OldPrivateMessage(text)
        if text in {"个人", "我的信息"}:
            await profile.myinfo_message(message)
        elif text == "导出":
            await attendance_actions.export_today_message(message)
        else:
            await attendance_actions.open_shift_web_app_message(message)
        return {
            "sessionReleased": released == [87001],
            "trace": normalize_old_replies(message.replies),
        }

    return {
        "AT-PRIVATE-MENU-USER": await old_menu_replies(
            menu, private=True, is_admin=False
        ),
        "AT-PRIVATE-MENU-ADMIN": await old_menu_replies(
            menu, private=True, is_admin=True
        ),
        "AT-GROUP-START": await old_menu_replies(
            menu, private=False, is_admin=False
        ),
        "AT-GROUP-UNKNOWN-IGNORED": ignored_group_trace,
        "AT-REGISTRATION-TEXT-BEGIN": normalize_old_replies(
            registration_message.replies
        ),
        "AT-ADMIN-EXPORT-TODAY": export_trace,
        "AT-SESSION-PROFILE-TEXT": await session_menu_trace(
            "个人",
            is_admin=False,
        ),
        "AT-SESSION-MYINFO-TEXT": await session_menu_trace(
            "我的信息",
            is_admin=False,
        ),
        "AT-SESSION-EXPORT-NONADMIN": await session_menu_trace(
            "导出",
            is_admin=False,
        ),
        "AT-SESSION-SHIFT-NONADMIN": await session_menu_trace(
            "班表",
            is_admin=False,
        ),
        "AT-SESSION-SHIFT-ALIAS-NONADMIN": await session_menu_trace(
            "班次",
            is_admin=False,
        ),
        "AT-SESSION-EXPORT-ADMIN": await session_menu_trace(
            "导出",
            is_admin=True,
        ),
        "AT-SESSION-SHIFT-ADMIN": await session_menu_trace(
            "班表",
            is_admin=True,
        ),
    }


class OldPrivateMessage:
    chat = SimpleNamespace(type="private", id=87001)
    from_user = SimpleNamespace(id=87001)

    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[tuple[str, Any]] = []

    async def reply(self, text: str, *, reply_markup: Any = None) -> None:
        self.replies.append((text, reply_markup))


async def old_export_trace(attendance_actions: Any) -> list[dict[str, Any]]:
    attendance_actions.admin_list_repo.is_admin_by_tg_id = lambda *, tg_id: True
    attendance_actions.load_daily_report_config = lambda: SimpleNamespace(
        timezone_name="Asia/Shanghai"
    )
    attendance_actions.attendance_export_service.today_in_tz = lambda **_kwargs: date(
        2026,
        8,
        8,
    )

    async def collect_rows(**_kwargs: object) -> list[object]:
        return []

    attendance_actions.attendance_export_service.collect_rows_for_range = collect_rows
    attendance_actions.attendance_export_service.build_pivot_and_overview = (
        lambda **_kwargs: ("pivot", SimpleNamespace(expected_count=0), [date(2026, 8, 8)])
    )
    attendance_actions.attendance_export_service.encode_attendance_export_xlsx = (
        lambda **_kwargs: b"parity-xlsx"
    )
    calls: list[dict[str, Any]] = []

    class StatusMessage:
        async def delete(self) -> None:
            calls.append({"method": "deleteMessage", "target": "progress"})

    class ExportMessage:
        chat = SimpleNamespace(type="private", id=87001)
        bot = object()

        async def reply(self, text: str) -> StatusMessage:
            calls.append({
                "method": "sendMessage",
                "text": text,
                "replyToInput": True,
            })
            return StatusMessage()

        async def reply_document(self, *, document: Any, caption: str) -> None:
            calls.append({
                "method": "sendDocument",
                "caption": caption,
                "fileName": document.filename,
                "contentBase64": base64.b64encode(document.data).decode("ascii"),
                "replyToInput": True,
            })

    class ExportCallback:
        data = "act:export:today"
        from_user = SimpleNamespace(id=87001)
        message = ExportMessage()

        async def answer(self) -> None:
            calls.append({"method": "answerCallbackQuery"})

    await attendance_actions.export_range_callback(ExportCallback())
    return calls


async def old_menu_replies(
    menu: Any,
    *,
    private: bool,
    is_admin: bool,
) -> dict[str, Any]:
    class FakeMessage:
        chat = SimpleNamespace(
            type="private" if private else "supergroup",
            id=87001 if private else -10087001,
        )
        from_user = SimpleNamespace(id=87001)

        def __init__(self) -> None:
            self.replies: list[tuple[str, Any]] = []

        async def reply(self, text: str, *, reply_markup: Any) -> None:
            self.replies.append((text, reply_markup))

    message = FakeMessage()
    cleared: list[int] = []
    menu.load_attendance_bot_owner = lambda: "ux_assistant"
    menu.register_service.clear_waiting_register_input = (
        lambda **kwargs: cleared.append(int(kwargs["tg_id"]))
    )
    menu.is_admin_by_tg_id = lambda *, tg_id: is_admin
    await menu._send_actions_menu(message)
    return {
        "ownerSessionClears": cleared,
        "trace": normalize_old_replies(message.replies),
    }


async def old_ignored_group_trace() -> list[dict[str, Any]]:
    from handlers.admin_export_test import router as admin_export_test_router  # type: ignore[import-not-found]
    from handlers.admin_test import router as admin_test_router  # type: ignore[import-not-found]
    from handlers.attendance_actions import router as attendance_actions_router  # type: ignore[import-not-found]
    from handlers.checkin import router as checkin_router  # type: ignore[import-not-found]
    from handlers.menu import router as menu_router  # type: ignore[import-not-found]
    from handlers.profile import router as profile_router  # type: ignore[import-not-found]
    from handlers.register import router as register_router  # type: ignore[import-not-found]

    aiogram = importlib.import_module("aiogram")
    Bot = aiogram.Bot
    Dispatcher = aiogram.Dispatcher
    UNHANDLED = importlib.import_module(
        "aiogram.dispatcher.event.bases"
    ).UNHANDLED
    MemoryStorage = importlib.import_module(
        "aiogram.fsm.storage.memory"
    ).MemoryStorage
    Update = importlib.import_module("aiogram.types").Update
    bot = Bot(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    dispatcher = Dispatcher(storage=MemoryStorage())
    for router in (
        admin_test_router,
        admin_export_test_router,
        attendance_actions_router,
        menu_router,
        profile_router,
        register_router,
        checkin_router,
    ):
        dispatcher.include_router(router)
    results: list[dict[str, Any]] = []
    try:
        for update_value in ignored_group_updates():
            result = await dispatcher.feed_update(
                bot,
                Update.model_validate(update_value),
            )
            results.append({
                "actions": [],
                "session": "UNCHANGED",
                "unhandled": result is UNHANDLED,
            })
    finally:
        await bot.session.close()
    return results


def normalize_old_replies(replies: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "method": "sendMessage",
            "text": text,
            "replyToInput": True,
            "replyMarkup": normalize_markup(
                markup.model_dump(exclude_none=True) if markup is not None else None
            ),
        }
        for text, markup in replies
    ]


async def current_trace() -> dict[str, Any]:
    from gateway_provider import event_module, export_module  # type: ignore[import-not-found]
    from gateway_provider.contracts import (  # type: ignore[import-not-found]
        GatewayEventRequest,
        event_response_value,
    )

    def private_response(is_admin: bool) -> dict[str, Any]:
        cleared: list[int] = []
        event_module.register_service.clear_waiting_register_input = (
            lambda _cursor, *, tg_id: cleared.append(tg_id)
        )
        event_module.is_admin = lambda _cursor, *, tg_id: is_admin
        export_module.is_admin = lambda _cursor, *, tg_id: is_admin
        request = GatewayEventRequest.model_validate(
            private_event(),
            strict=True,
        )
        response = event_module._private_menu_response(
            request,
            object(),
            chat_id=87001,
            reply_to_message_id=701,
            actor_id=87001,
            shift_web_app_url="https://attendance.example.test/shift-app/index.html?year_month=2026-08",
        )
        return {
            "ownerSessionClears": cleared,
            "trace": normalize_current_actions(
                event_response_value(response)["actions"]
            ),
        }

    group_request = GatewayEventRequest.model_validate(group_start_event(), strict=True)
    group_update = group_request.telegramUpdate
    group_response = event_module._group_menu_response(group_request, group_update)
    ignored_group_trace = []
    for update_value in ignored_group_updates():
        ignored_request = GatewayEventRequest.model_validate(
            gateway_event(update_value),
            strict=True,
        )
        ignored_response = event_module._process_attendance_event(
            ignored_request,
            object(),
            object(),
            shift_web_app_public_url="https://attendance.example.test",
        )
        ignored_value = event_response_value(ignored_response)
        ignored_group_trace.append({
            "actions": normalize_current_actions(ignored_value["actions"]),
            "session": ignored_value["session"]["directive"],
            "unhandled": True,
        })
    event_module.registrations_repo.get_by_tg_id_cur = lambda _cursor, *, tg_id: None
    event_module.register_service.mark_waiting_register_input = (
        lambda _cursor, *, tg_id, private_chat_id: None
    )
    registration_request = GatewayEventRequest.model_validate(
        registration_begin_event(),
        strict=True,
    )
    registration_update = registration_request.telegramUpdate
    registration_response = event_module._begin_registration_message(
        registration_request,
        object(),
        registration_update,
    )
    export_module.is_admin = lambda _cursor, *, tg_id: True

    async def collect_rows(**_kwargs: object) -> list[object]:
        return []

    export_module.attendance_export_service.collect_rows_for_range = collect_rows
    export_module.attendance_export_service.build_pivot_and_overview = (
        lambda **_kwargs: ("pivot", SimpleNamespace(expected_count=0), [date(2026, 8, 8)])
    )
    export_module.attendance_export_service.encode_attendance_export_xlsx = (
        lambda **_kwargs: b"parity-xlsx"
    )
    export_module._deterministic_xlsx = lambda payload, **_kwargs: payload
    export_request = GatewayEventRequest.model_validate(
        export_callback_event(),
        strict=True,
    )
    export_response = await asyncio.to_thread(
        export_module.process_export_callback,
        export_request,
        object(),
        export_request.telegramUpdate,
    )

    def session_menu_trace(text: str, *, is_admin: bool) -> dict[str, Any]:
        released: list[int] = []
        event_module.register_service.clear_waiting_register_input = (
            lambda _cursor, *, tg_id: released.append(tg_id)
        )
        event_module.profile_text_for_tg_id = lambda *_args, **_kwargs: (
            "你还未完成注册，请先注册后再查看我的信息。"
        )
        event_module.is_admin = lambda _cursor, *, tg_id: is_admin
        export_module.is_admin = lambda _cursor, *, tg_id: is_admin
        request = GatewayEventRequest.model_validate(
            registration_session_event(text),
            strict=True,
        )
        response = event_module._process_registration_text(
            request,
            object(),
            request.telegramUpdate,
            shift_web_app_public_url="https://attendance.example.test",
        )
        value = event_response_value(response)
        return {
            "sessionReleased": (
                released == [87001]
                and value["session"] == {"directive": "RELEASE"}
            ),
            "trace": normalize_current_actions(value["actions"]),
        }

    return {
        "AT-PRIVATE-MENU-USER": private_response(False),
        "AT-PRIVATE-MENU-ADMIN": private_response(True),
        "AT-GROUP-START": {
            "ownerSessionClears": [],
            "trace": normalize_current_actions(
                event_response_value(group_response)["actions"]
            ),
        },
        "AT-GROUP-UNKNOWN-IGNORED": ignored_group_trace,
        "AT-REGISTRATION-TEXT-BEGIN": normalize_current_actions(
            event_response_value(registration_response)["actions"]
        ),
        "AT-ADMIN-EXPORT-TODAY": normalize_current_export_actions(
            event_response_value(export_response)["actions"]
        ),
        "AT-SESSION-PROFILE-TEXT": session_menu_trace(
            "个人",
            is_admin=False,
        ),
        "AT-SESSION-MYINFO-TEXT": session_menu_trace(
            "我的信息",
            is_admin=False,
        ),
        "AT-SESSION-EXPORT-NONADMIN": session_menu_trace(
            "导出",
            is_admin=False,
        ),
        "AT-SESSION-SHIFT-NONADMIN": session_menu_trace(
            "班表",
            is_admin=False,
        ),
        "AT-SESSION-SHIFT-ALIAS-NONADMIN": session_menu_trace(
            "班次",
            is_admin=False,
        ),
        "AT-SESSION-EXPORT-ADMIN": session_menu_trace(
            "导出",
            is_admin=True,
        ),
        "AT-SESSION-SHIFT-ADMIN": session_menu_trace(
            "班表",
            is_admin=True,
        ),
    }


def ignored_group_updates() -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for event_number, text in (
        (9101, "/unknown"),
        (9102, "ordinary reply"),
        (9103, "@uxassistant_bot unrelated"),
        (9104, "ordinary edited text"),
    ):
        message = {
            "message_id": event_number,
            "date": 1786176120,
            "chat": {
                "id": -10087001,
                "type": "supergroup",
                "title": "Mutable title",
            },
            "from": {
                "id": 87001,
                "is_bot": False,
                "first_name": "Parity",
            },
            "text": text,
        }
        if event_number == 9102:
            message["reply_to_message"] = {
                "message_id": 9000,
                "date": 1786176000,
                "chat": message["chat"],
                "from": {
                    "id": 90001,
                    "is_bot": True,
                    "first_name": "Gateway",
                },
                "text": "bot prompt",
            }
        key = "edited_message" if event_number == 9104 else "message"
        updates.append({"update_id": event_number, key: message})
    return updates


def gateway_event(update: dict[str, Any]) -> dict[str, Any]:
    update_id = int(update["update_id"])
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-group-ignored-{update_id}",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "conversationId": "telegram:chat:-10087001",
        "receivedAt": "2026-08-08T08:02:00Z",
        "telegramUpdate": update,
    }


def normalize_current_export_actions(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for action in actions:
        if action["type"] == "ANSWER_CALLBACK":
            normalized.append({"method": "answerCallbackQuery"})
        elif action["type"] == "SEND_MESSAGE":
            normalized.append({
                "method": "sendMessage",
                "text": action["text"],
                "replyToInput": action.get("replyToMessageId") == 704,
            })
        elif action["type"] == "SEND_DOCUMENT":
            normalized.append({
                "method": "sendDocument",
                "caption": action["caption"],
                "fileName": action["document"]["fileName"],
                "contentBase64": action["document"]["contentBase64"],
                "replyToInput": action.get("replyToMessageId") == 704,
            })
        elif action["type"] == "DELETE_MESSAGE":
            normalized.append({"method": "deleteMessage", "target": "progress"})
        else:
            raise AssertionError(f"Unsupported export action: {action!r}")
    return normalized


def normalize_current_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "method": "sendMessage",
            "text": action["text"],
            "replyToInput": action.get("replyToMessageId") == 701
            or action.get("replyToMessageId") == 702,
            "replyMarkup": normalize_markup(action.get("replyMarkup")),
        }
        for action in actions
        if action["type"] == "SEND_MESSAGE"
    ]


def normalize_markup(markup: Any) -> Any:
    if not isinstance(markup, dict):
        return None
    if markup.get("remove_keyboard") is True or markup.get("removeKeyboard") is True:
        return {"kind": "REMOVE_KEYBOARD"}
    keyboard = markup.get("inline_keyboard") or markup.get("inlineKeyboard")
    if keyboard is not None:
        return {
            "kind": "INLINE_KEYBOARD",
            "rows": [
                [
                    {
                        "text": button["text"],
                        "action": button_action(button),
                        **(
                            {"url": web_app_url(button)}
                            if button_action(button) == "WEB_APP"
                            else {}
                        ),
                    }
                    for button in row
                ]
                for row in keyboard
            ],
        }
    reply_keyboard = markup.get("keyboard")
    if reply_keyboard is not None:
        return {
            "kind": "REPLY_KEYBOARD",
            "rows": [[button["text"] for button in row] for row in reply_keyboard],
            "isPersistent": markup.get("is_persistent", markup.get("isPersistent")),
            "resizeKeyboard": markup.get("resize_keyboard", markup.get("resizeKeyboard")),
            "inputFieldPlaceholder": markup.get(
                "input_field_placeholder",
                markup.get("inputFieldPlaceholder"),
            ),
        }
    raise AssertionError(f"Unsupported reply markup: {markup!r}")


def button_action(button: dict[str, Any]) -> str:
    if "web_app" in button or "webAppUrl" in button:
        return "WEB_APP"
    return "CALLBACK"


def web_app_url(button: dict[str, Any]) -> str:
    if "webAppUrl" in button:
        return str(button["webAppUrl"])
    return str(button["web_app"]["url"])


def private_event() -> dict[str, Any]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-parity-private-menu",
        "target": "ATTENDANCE",
        "routeReason": "COMMAND",
        "conversationId": "telegram:private:87001",
        "receivedAt": "2026-08-09T01:00:00.000Z",
        "telegramUpdate": {
            "update_id": 7101,
            "message": {
                "message_id": 701,
                "date": 1_786_204_800,
                "chat": {"id": 87001, "type": "private"},
                "from": {"id": 87001, "is_bot": False, "first_name": "Parity"},
                "text": "/attendance",
            },
        },
    }


def group_start_event() -> dict[str, Any]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-parity-group-menu",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "conversationId": "telegram:chat:-10087001",
        "receivedAt": "2026-08-09T01:00:00.000Z",
        "telegramUpdate": {
            "update_id": 7102,
            "message": {
                "message_id": 702,
                "date": 1_786_204_800,
                "chat": {"id": -10087001, "type": "supergroup"},
                "from": {"id": 87001, "is_bot": False, "first_name": "Parity"},
                "text": "/start",
            },
        },
    }


def registration_begin_event() -> dict[str, Any]:
    event = private_event()
    event["eventId"] = "evt-attendance-parity-registration-begin"
    update = event["telegramUpdate"]
    assert isinstance(update, dict)
    message = update["message"]
    assert isinstance(message, dict)
    message["text"] = "注册"
    return event


def registration_session_event(text: str) -> dict[str, Any]:
    event = private_event()
    event["eventId"] = "evt-attendance-parity-registration-session"
    event["routeReason"] = "CONVERSATION_SESSION"
    update = event["telegramUpdate"]
    assert isinstance(update, dict)
    message = update["message"]
    assert isinstance(message, dict)
    message["text"] = text
    return event


def export_callback_event() -> dict[str, Any]:
    event = private_event()
    event["eventId"] = "evt-attendance-parity-export-today"
    event["routeReason"] = "CALLBACK_NAMESPACE"
    event["receivedAt"] = "2026-08-08T08:00:00Z"
    event["telegramUpdate"] = {
        "update_id": 7104,
        "callback_query": {
            "id": "callback-export-7104",
            "from": {
                "id": 87001,
                "is_bot": False,
                "first_name": "Parity",
            },
            "message": {
                "message_id": 704,
                "date": 1_786_204_800,
                "chat": {"id": 87001, "type": "private"},
                "text": "请选择导出范围：",
            },
            "chat_instance": "instance-export-7104",
            "data": "att:export:today",
        },
    }
    return event


if __name__ == "__main__":
    main()
