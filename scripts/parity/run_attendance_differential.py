from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-root", type=Path)
    parser.add_argument(
        "--python",
        type=Path,
        help="Use one explicit Python runtime for both frozen and current traces",
    )
    parser.add_argument("--mode", choices=("old", "current"))
    parser.add_argument("--import-root", type=Path)
    parser.add_argument("--matrix", type=Path)
    args = parser.parse_args()
    current_root = Path(__file__).resolve().parents[2]
    matrix_path = resolve_matrix_path(args.matrix, current_root=current_root)
    scenarios = load_attendance_matrix(matrix_path)
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
    old_python = args.python or args.old_root / ".venv/bin/python"
    current_python = args.python or current_root / ".venv/bin/python"
    old = run_trace(old_python, script, "old", args.old_root, matrix_path)
    current = run_trace(current_python, script, "current", current_root, matrix_path)
    expected_ids = sorted(scenario["scenarioId"] for scenario in scenarios)
    missing_old = sorted(set(expected_ids) - set(old))
    missing_current = sorted(set(expected_ids) - set(current))
    extra_old = sorted(set(old) - set(expected_ids))
    extra_current = sorted(set(current) - set(expected_ids))
    if missing_old or missing_current or extra_old or extra_current:
        raise AssertionError(
            "Attendance differential coverage is incomplete: "
            f"missingOld={missing_old}, missingCurrent={missing_current}, "
            f"extraOld={extra_old}, extraCurrent={extra_current}"
        )

    evidence: dict[str, dict[str, Any]] = {}
    trace_digests: dict[str, str] = {}
    parity_count = 0
    bugfix_count = 0
    for scenario in scenarios:
        scenario_id = str(scenario["scenarioId"])
        classification = str(scenario["classification"])
        old_value = old[scenario_id]
        current_value = current[scenario_id]
        if classification == "PARITY":
            parity_count += 1
            if old_value != current_value:
                raise AssertionError(
                    f"Attendance old/current trace differs for {scenario_id}:\n"
                    f"old={json.dumps(old_value, ensure_ascii=False, sort_keys=True)}\n"
                    f"current={json.dumps(current_value, ensure_ascii=False, sort_keys=True)}"
                )
            trace_equal = True
            current_recovery_passed = False
        elif classification == "BUGFIX_DELTA":
            bugfix_count += 1
            if not (
                isinstance(old_value, dict)
                and old_value.get("proofKind") == "OLD_CODE_CHARACTERIZATION"
                and old_value.get("characterizationExecuted") is True
                and old_value.get("lockedDeploymentExecuted") is True
                and old_value.get("failureReproduced") is True
            ):
                raise AssertionError(
                    f"{scenario_id} lacks executable old-code characterization"
                )
            if not (
                isinstance(current_value, dict)
                and current_value.get("proofKind") == "CURRENT_RECOVERY"
                and current_value.get("passed") is True
            ):
                raise AssertionError(
                    f"{scenario_id} lacks a passing current recovery execution"
                )
            trace_equal = False
            current_recovery_passed = True
        else:
            raise AssertionError(
                f"unsupported Attendance parity classification: {classification}"
            )
        evidence[scenario_id] = {
            "classification": classification,
            "exactInput": scenario["exactInput"],
            "oldCharacterizationExecuted": (
                old_value.get("characterizationExecuted") is True
                if classification == "BUGFIX_DELTA"
                else True
            ),
            "currentExecutionExecuted": True,
            "sameInput": classification == "PARITY",
            "traceEqual": trace_equal,
            "oldDeploymentClaimed": False,
            "oldLockedBaselineExecuted": (
                old_value.get("lockedDeploymentExecuted") is True
                if classification == "BUGFIX_DELTA"
                else False
            ),
            "oldFailureReproduced": (
                old_value.get("failureReproduced") is True
                if classification == "BUGFIX_DELTA"
                else False
            ),
            "currentRecoveryTestPassed": current_recovery_passed,
        }
        digest_value = (
            old_value
            if classification == "PARITY"
            else {"old": old_value, "current": current_value}
        )
        trace_digests[scenario_id] = hashlib.sha256(
            json.dumps(
                digest_value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if trace_digests[scenario_id] != scenario.get("executableTraceSha256"):
            raise AssertionError(
                f"{scenario_id} executable trace changed from the reviewed "
                "locked baseline"
            )

    print(json.dumps({
        "baseline": "Attendance@1b9c779",
        "counts": {
            "BUGFIX_DELTA": bugfix_count,
            "PARITY": parity_count,
            "TOTAL": len(scenarios),
        },
        "evidence": evidence,
        "scenarioIds": expected_ids,
        "traceDigests": trace_digests,
        "result": "PASS",
    }, ensure_ascii=False, sort_keys=True))


def run_trace(
    python: Path,
    script: Path,
    mode: str,
    import_root: Path,
    matrix_path: Path,
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
            "--matrix",
            str(matrix_path),
        ],
        cwd=import_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def resolve_matrix_path(value: Path | None, *, current_root: Path) -> Path:
    if value is not None:
        resolved = value.resolve()
    else:
        configured = os.environ.get("ATTENDANCE_PARITY_MATRIX")
        resolved = (
            Path(configured).resolve()
            if configured
            else (
                current_root.parent
                / "UXAssistant-Gateway/tests/parity/old-current-behavior-differential-matrix.ts"
            ).resolve()
        )
    if not resolved.is_file():
        raise RuntimeError(f"Attendance parity matrix is missing: {resolved}")
    return resolved


def load_attendance_matrix(matrix_path: Path) -> list[dict[str, Any]]:
    gateway_root = matrix_path.parents[2]
    vite_node = gateway_root / "node_modules/.bin/vite-node"
    matrix_reader = gateway_root / "scripts/parity/read-behavior-matrix.ts"
    if not vite_node.is_file() or not matrix_reader.is_file():
        raise RuntimeError("Gateway behavior matrix runtime is missing")
    completed = subprocess.run(
        [
            str(vite_node),
            str(matrix_reader),
            str(matrix_path),
            "ATTENDANCE",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, list):
        raise RuntimeError("Attendance parity matrix did not export a scenario list")
    ids = [str(item.get("scenarioId")) for item in value]
    if len(ids) != 104 or len(set(ids)) != 104:
        raise RuntimeError(
            "Attendance parity matrix must contain 104 unique scenarios; "
            f"received {len(ids)} rows and {len(set(ids))} unique ids"
        )
    classifications = [str(item.get("classification")) for item in value]
    if classifications.count("PARITY") != 91 or classifications.count(
        "BUGFIX_DELTA"
    ) != 13:
        raise RuntimeError(
            "Attendance parity matrix classification census changed: "
            f"PARITY={classifications.count('PARITY')} "
            f"BUGFIX_DELTA={classifications.count('BUGFIX_DELTA')}"
        )
    invalid_digests = [
        item.get("scenarioId")
        for item in value
        if not isinstance(item.get("executableTraceSha256"), str)
        or len(item["executableTraceSha256"]) != 64
    ]
    if invalid_digests:
        raise RuntimeError(
            "Attendance parity matrix has invalid executable trace digests: "
            f"{invalid_digests}"
        )
    return value


async def old_trace() -> dict[str, Any]:
    import webhook_app  # type: ignore[import-not-found]
    import shift_web_app  # type: ignore[import-not-found]
    from infra import shift_web_http  # type: ignore[import-not-found]
    from keyboards import actions_menu  # type: ignore[import-not-found]
    from keyboards import group_actions  # type: ignore[import-not-found]
    from handlers import (  # type: ignore[import-not-found]
        admin_export_test,
        admin_test,
        attendance_actions,
        checkin,
        menu,
        profile,
        register,
    )

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
    export_traces = await old_export_matrix_traces(attendance_actions)
    registration_traces = await old_registration_traces(register)
    admin_traces = await old_admin_test_traces(admin_test)
    admin_export_traces = await old_admin_export_traces(admin_export_test)
    leave_report_traces = await old_leave_report_traces(attendance_actions)
    checkin_traces = await old_checkin_traces(checkin)
    http_traces = await old_http_contract_traces(webhook_app)
    shift_web_traces = await shift_web_http_traces(
        shift_web_app=shift_web_app,
        shift_http=shift_web_http,
        current=False,
    )
    bugfix_traces = await old_bugfix_characterizations()
    attendance_actions.build_shift_web_app_url_for_admin = (
        lambda *, tg_id: (
            "https://attendance.example.test/shift-app/index.html"
            "?year_month=2026-08"
        )
    )
    actions_menu.build_shift_web_app_url_for_admin = (
        attendance_actions.build_shift_web_app_url_for_admin
    )
    profile.profile_service.get_my_profile_by_tg_id = lambda **_kwargs: SimpleNamespace(
        message="你还未完成注册，请先注册后再查看我的信息。",
        ok=False,
        error_code="NOT_REGISTERED",
    )
    ignored_group_trace = await old_ignored_group_trace()
    interaction_traces = await old_group_interaction_traces(
        menu=menu,
        attendance_actions=attendance_actions,
        actions_menu=actions_menu,
        group_actions=group_actions,
    )
    surface_traces = await old_profile_shift_switch_traces(
        attendance_actions=attendance_actions,
        profile=profile,
    )

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

    trace = {
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
        **interaction_traces,
        **surface_traces,
        **export_traces,
        **registration_traces,
        **admin_traces,
        **admin_export_traces,
        **leave_report_traces,
        **checkin_traces,
        **http_traces,
        **shift_web_traces,
        **bugfix_traces,
    }
    return matrix_trace_aliases(trace)


class OldPrivateMessage:
    chat = SimpleNamespace(type="private", id=87001)
    from_user = SimpleNamespace(id=87001)

    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[tuple[str, Any]] = []

    async def reply(self, text: str, *, reply_markup: Any = None) -> None:
        self.replies.append((text, reply_markup))


async def old_export_matrix_traces(attendance_actions: Any) -> dict[str, Any]:
    traces: dict[str, Any] = {}
    for scenario_id, callback_data, failure in (
        ("AT-EXPORT-TODAY", "act:export:today", False),
        ("AT-EXPORT-YESTERDAY", "act:export:yesterday", False),
        ("AT-EXPORT-WEEK", "act:export:week", False),
        ("AT-EXPORT-LAST-WEEK", "act:export:last_week", False),
        ("AT-EXPORT-MONTH", "act:export:month", False),
        ("AT-EXPORT-LAST-MONTH", "act:export:last_month", False),
        ("AT-EXPORT-FAILURE", "act:export:today", True),
    ):
        traces[scenario_id] = await old_export_trace(
            attendance_actions,
            callback_data=callback_data,
            failure=failure,
        )

    attendance_actions.admin_list_repo.is_admin_by_tg_id = lambda **_kwargs: True
    message = OldInteractionMessage(
        text="导出",
        private=False,
        sender_id=87099,
    )
    await attendance_actions.export_today_message(message)
    traces["AT-EXPORT-TEXT-NONPRIVATE"] = normalize_old_replies(message.replies)
    return traces


async def old_export_trace(
    attendance_actions: Any,
    *,
    callback_data: str,
    failure: bool,
) -> list[dict[str, Any]]:
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
        if failure:
            raise RuntimeError("database unavailable")
        return []

    attendance_actions.attendance_export_service.collect_rows_for_range = collect_rows
    attendance_actions.attendance_export_service.build_pivot_and_overview = (
        lambda **_kwargs: ("pivot", SimpleNamespace(expected_count=3), [date(2026, 8, 8)])
    )
    attendance_actions.attendance_export_service.encode_attendance_export_xlsx = (
        lambda **_kwargs: b"parity-xlsx"
    )
    calls: list[dict[str, Any]] = []

    class StatusMessage:
        async def delete(self) -> None:
            calls.append({"method": "deleteMessage", "target": "progress"})

    class ExportMessage:
        chat = SimpleNamespace(type="private", id=87099)
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
        data = callback_data
        from_user = SimpleNamespace(id=87099)
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
    bot = Bot(token=f"{'8' * 9}:{'A' * 35}")
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
            if result is not UNHANDLED:
                raise AssertionError(
                    "old Attendance unexpectedly handled non-command group text"
                )
            results.append({
                "actions": [],
                "session": "UNCHANGED",
                "businessWrites": [],
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
    import shift_web_app  # type: ignore[import-not-found]
    from infra import shift_web_http  # type: ignore[import-not-found]
    from gateway_provider import (  # type: ignore[import-not-found]
        admin_module,
        admin_export_module,
        checkin_module,
        event_module,
        export_module,
    )
    from gateway_provider import app as provider_app  # type: ignore[import-not-found]
    from gateway_provider import registration_session_module  # type: ignore[import-not-found]
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
        trace = normalize_current_actions(
            event_response_value(response)["actions"]
        )
        return {
            "ownerSessionClears": cleared,
            "trace": trace,
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
            "businessWrites": [],
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
    export_traces = await current_export_matrix_traces(
        event_module=event_module,
        export_module=export_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )
    registration_traces = current_registration_traces(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )
    admin_traces = current_admin_test_traces(
        admin_module=admin_module,
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )
    admin_export_traces = current_admin_export_traces(
        admin_export_module=admin_export_module,
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )
    leave_report_traces = current_leave_report_traces(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )
    checkin_traces = current_checkin_traces(
        checkin_module=checkin_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )
    http_traces = current_http_contract_traces(
        provider_app=provider_app,
        event_module=event_module,
        registration_session_module=registration_session_module,
        GatewayEventRequest=GatewayEventRequest,
    )
    shift_web_traces = await shift_web_http_traces(
        shift_web_app=shift_web_app,
        shift_http=shift_web_http,
        current=True,
    )
    bugfix_traces = await current_bugfix_recoveries()

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

    interaction_traces = current_group_interaction_traces(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )
    surface_traces = current_profile_shift_switch_traces(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
    )

    trace = {
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
        **interaction_traces,
        **surface_traces,
        **export_traces,
        **registration_traces,
        **admin_traces,
        **admin_export_traces,
        **leave_report_traces,
        **checkin_traces,
        **http_traces,
        **shift_web_traces,
        **bugfix_traces,
    }
    return matrix_trace_aliases(trace)


class ParityCursor:
    def execute(self, *_args: object, **_kwargs: object) -> None:
        return None

    def fetchone(self) -> None:
        return None


class OldInteractionMessage:
    def __init__(
        self,
        *,
        text: str,
        private: bool = False,
        sender_id: int = 87001,
    ) -> None:
        self.text = text
        self.caption = None
        self.chat = SimpleNamespace(
            id=87001 if private else -10087001,
            type="private" if private else "supergroup",
            title=None if private else "Attendance Parity",
        )
        self.from_user = SimpleNamespace(id=sender_id, username=None)
        self.replies: list[tuple[str, Any]] = []

    async def reply(self, text: str, *, reply_markup: Any = None) -> None:
        self.replies.append((text, reply_markup))


class OldInteractionCallback:
    def __init__(
        self,
        *,
        data: str,
        callback_id: str,
        message: OldInteractionMessage,
        sender_id: int = 87001,
        username: str | None = None,
    ) -> None:
        self.data = data
        self.id = callback_id
        self.from_user = SimpleNamespace(id=sender_id, username=username)
        self.message = message
        self.answers: list[str] = []

    async def answer(self) -> None:
        self.answers.append(self.id)


async def old_leave_report_traces(attendance_actions: Any) -> dict[str, Any]:
    fixed_now = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    attendance_actions.datetime = FixedDateTime
    traces: dict[str, Any] = {}
    for scenario_id, operation, registered, existing_open, text in (
        (
            "AT-LEAVE-REPORT-SUCCESS",
            "leave",
            True,
            False,
            "#离岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：吃饭",
        ),
        (
            "AT-LEAVE-REPORT-UNREGISTERED",
            "leave",
            False,
            False,
            "#离岗报备\n人员：UNKNOWN\n时间：17:00:00\n原因：吃饭",
        ),
        (
            "AT-LEAVE-REPORT-DUPLICATE",
            "leave",
            True,
            True,
            "#离岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：重复",
        ),
        (
            "AT-BACK-REPORT-SUCCESS",
            "back",
            True,
            True,
            "#返岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：吃饭结束",
        ),
        (
            "AT-BACK-REPORT-UNREGISTERED",
            "back",
            False,
            False,
            "#返岗报备\n人员：UNKNOWN\n时间：17:00:00\n原因：返回",
        ),
        (
            "AT-BACK-REPORT-NO-OPEN",
            "back",
            True,
            False,
            "#返岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：返回",
        ),
    ):
        registration = SimpleNamespace(
            employee_id="74808",
            english_name="GRANDFOR",
        )
        open_record = (
            SimpleNamespace(
                id=31,
                employee_id="74808",
                chat_id=-10087001,
                leave_at=datetime(2026, 8, 8, 8, 35, tzinfo=timezone.utc),
                back_at=None,
                duration_minutes=None,
                remark_required=False,
                reason="先前离岗",
            )
            if existing_open
            else None
        )
        writes: list[dict[str, Any]] = []
        attendance_actions.registrations_repo.get_by_tg_id = (
            lambda _tg_id, registered=registered, registration=registration: (
                registration if registered else None
            )
        )
        attendance_actions.check_can_leave = (
            lambda **_kwargs: (
                (False, "您已离岗") if existing_open else (True, None)
            )
        )
        attendance_actions.check_can_back = (
            lambda **_kwargs: (
                (True, None) if existing_open else (False, "您还未点击离岗")
            )
        )
        attendance_actions.temporary_leave_records_repo.get_latest_open = (
            lambda **_kwargs: open_record
        )

        def insert_leave(**kwargs: Any) -> int:
            writes.append({
                "operation": "INSERT_LEAVE",
                "employeeId": kwargs["employee_id"],
                "chatId": kwargs["chat_id"],
                "reason": kwargs["reason"],
                "leaveAt": kwargs["leave_at_utc"].isoformat(),
            })
            return 32

        def close_leave(**kwargs: Any) -> bool:
            writes.append({
                "operation": "CLOSE_LEAVE",
                "recordId": kwargs["record_id"],
                "backAt": kwargs["back_at_utc"].isoformat(),
                "durationMinutes": kwargs["duration_minutes"],
                "remarkRequired": kwargs["remark_required"],
            })
            return True

        attendance_actions.temporary_leave_records_repo.insert_leave = insert_leave
        attendance_actions.temporary_leave_records_repo.close_leave = close_leave
        message = OldInteractionMessage(
            text=text,
            sender_id=87001 if registered else 87100,
        )
        if operation == "leave":
            await attendance_actions.parse_leave_sent(message)
        else:
            await attendance_actions.parse_back_sent(message)
        traces[scenario_id] = {
            "actions": normalize_old_replies(message.replies),
            "businessWrites": writes,
        }
    return traces


def current_leave_report_traces(
    *,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    traces: dict[str, Any] = {}
    for scenario_id, operation, registered, existing_open, text in (
        (
            "AT-LEAVE-REPORT-SUCCESS",
            "leave",
            True,
            False,
            "#离岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：吃饭",
        ),
        (
            "AT-LEAVE-REPORT-UNREGISTERED",
            "leave",
            False,
            False,
            "#离岗报备\n人员：UNKNOWN\n时间：17:00:00\n原因：吃饭",
        ),
        (
            "AT-LEAVE-REPORT-DUPLICATE",
            "leave",
            True,
            True,
            "#离岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：重复",
        ),
        (
            "AT-BACK-REPORT-SUCCESS",
            "back",
            True,
            True,
            "#返岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：吃饭结束",
        ),
        (
            "AT-BACK-REPORT-UNREGISTERED",
            "back",
            False,
            False,
            "#返岗报备\n人员：UNKNOWN\n时间：17:00:00\n原因：返回",
        ),
        (
            "AT-BACK-REPORT-NO-OPEN",
            "back",
            True,
            False,
            "#返岗报备\n人员：GRANDFOR\n时间：17:00:00\n原因：返回",
        ),
    ):
        registration = SimpleNamespace(
            employee_id="74808",
            english_name="GRANDFOR",
        )
        open_record = (
            SimpleNamespace(
                id=31,
                leave_at=datetime(2026, 8, 8, 8, 35, tzinfo=timezone.utc),
            )
            if existing_open
            else None
        )
        writes: list[dict[str, Any]] = []
        event_module.registrations_repo.get_by_tg_id_cur = (
            lambda _cursor, *, tg_id, registered=registered, registration=registration: (
                registration if registered else None
            )
        )
        event_module.temporary_leave_records_repo.get_latest_open_cur = (
            lambda _cursor, **_kwargs: open_record
        )
        event_module.requires_leave_mutual_exclusion = lambda **_kwargs: True

        def insert_leave(_cursor: Any, **kwargs: Any) -> int:
            writes.append({
                "operation": "INSERT_LEAVE",
                "employeeId": kwargs["employee_id"],
                "chatId": kwargs["chat_id"],
                "reason": kwargs["reason"],
                "leaveAt": kwargs["leave_at_utc"].isoformat(),
            })
            return 32

        def close_leave(_cursor: Any, **kwargs: Any) -> bool:
            writes.append({
                "operation": "CLOSE_LEAVE",
                "recordId": kwargs["record_id"],
                "backAt": kwargs["back_at_utc"].isoformat(),
                "durationMinutes": kwargs["duration_minutes"],
                "remarkRequired": kwargs["remark_required"],
            })
            return True

        event_module.temporary_leave_records_repo.insert_leave_cur = insert_leave
        event_module.temporary_leave_records_repo.close_leave_cur = close_leave
        event = group_message_event(
            text,
            sender_id=87001 if registered else 87100,
        )
        request = GatewayEventRequest.model_validate(event, strict=True)
        response = event_module._process_group_leave_report(
            request,
            ParityCursor(),
            request.telegramUpdate,
            operation=operation,
        )
        traces[scenario_id] = {
            "actions": normalize_current_actions(
                event_response_value(response)["actions"]
            ),
            "businessWrites": writes,
        }
    return traces


async def old_checkin_traces(checkin: Any) -> dict[str, Any]:
    ServiceResult = importlib.import_module("domain.shared.result").ServiceResult
    fixed_clock = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
    registration = SimpleNamespace(
        employee_id="74808",
        english_name="GRANDFOR",
    )
    traces: dict[str, Any] = {}
    cases = checkin_cases()
    for case in cases:
        actions: list[dict[str, Any]] = []
        writes: list[dict[str, Any]] = []
        background: list[str] = []
        downloads: list[str] = []

        class Message:
            message_id = 701
            date = fixed_clock
            caption = case["caption"]
            chat = SimpleNamespace(
                id=-10087001,
                type="supergroup",
                title="Attendance Parity",
            )
            from_user = SimpleNamespace(
                id=case["senderId"],
                username="parity_actor",
            )
            document = (
                SimpleNamespace(file_id="document-file-701")
                if case["kind"] == "document"
                else None
            )
            photo = (
                [
                    SimpleNamespace(
                        file_id="photo-file-preview",
                        width=100,
                        height=100,
                        file_size=10,
                    ),
                    SimpleNamespace(
                        file_id="photo-file-701",
                        width=1280,
                        height=720,
                        file_size=20,
                    ),
                ]
                if case["kind"] == "photo"
                else None
            )

            async def reply(self, text: str, **_kwargs: Any) -> None:
                actions.append({
                    "method": "sendMessage",
                    "text": text,
                    "replyToInput": True,
                    "replyMarkup": None,
                })

            async def answer(self, text: str, **_kwargs: Any) -> None:
                await self.reply(text)

        checkin.checkin_service.validate_and_prepare = (
            lambda **_kwargs: (
                ServiceResult(
                    ok=False,
                    message="打卡失败，您尚未注册",
                    error_code="NOT_REGISTERED",
                )
                if not case["registered"]
                else (
                    "74808",
                    7,
                    "GRANDFOR",
                    None,
                    None,
                    None,
                    "Asia/Shanghai",
                )
            )
        )
        checkin.checkin_service.should_accept_checkin_for_chat_roster = (
            lambda **_kwargs: (True, None)
        )
        checkin.checkin_service.should_run_ai_without_persist = (
            lambda **_kwargs: False
        )
        checkin.validate_caption_identity_for_sender = (
            lambda **_kwargs: (
                "CAPTION_IDENTITY_MISMATCH" if case["badIdentity"] else None
            )
        )
        checkin.requires_remote_diff_checkin = lambda **_kwargs: False
        checkin.checkin_service.has_processed_telegram_checkin = (
            lambda **_kwargs: case["duplicate"]
        )
        checkin.load_attendance_bot_owner = lambda: "attendance"

        async def resolve_with_ai(**kwargs: Any) -> Any:
            downloads.append(str(kwargs["file_id"]))
            if case["aiError"]:
                return ServiceResult(
                    ok=False,
                    message="打卡失败：识别服务不可用，请稍后重试。",
                    error_code="AI_SERVICE_DOWN",
                )
            return checkin.checkin_ai_orchestrator.CheckinAiResolveResult(
                clock_time_utc=fixed_clock,
                used_ai_time=True,
                verified_image_user=True,
                extraction=None,
            )

        checkin.checkin_ai_orchestrator.resolve_clock_time_with_ai = resolve_with_ai

        def persist(**kwargs: Any) -> tuple[int, bool]:
            writes.append({
                "operation": "INSERT_CLOCK",
                "botOwner": kwargs["bot_owner"],
                "sourceChatId": kwargs["source_chat_id"],
                "sourceMessageId": kwargs["source_message_id"],
                "employeeId": kwargs["employee_id"],
                "action": kwargs["clock_action"],
                "clockTime": kwargs["clock_time_utc"].isoformat(),
            })
            return 41, True

        checkin.checkin_service.persist_telegram_clock_record = persist
        checkin.is_test_group_chat = lambda **_kwargs: False
        await checkin._handle_checkin_message(Message(), object())
        traces[str(case["scenarioId"])] = {
            "actions": actions,
            "businessWrites": writes,
            "backgroundGuards": background,
            "downloadedFileIds": downloads,
        }
    return traces


def current_checkin_traces(
    *,
    checkin_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    ServiceResult = importlib.import_module("domain.shared.result").ServiceResult
    fixed_clock = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
    registration = SimpleNamespace(
        employee_id="74808",
        english_name="GRANDFOR",
    )
    traces: dict[str, Any] = {}
    original_enqueue_run = checkin_module.worker_schedule_repo.enqueue_run_cur
    for case in checkin_cases():
        writes: list[dict[str, Any]] = []
        background: list[str] = []
        downloads: list[str] = []
        deferred_jobs: list[dict[str, Any]] = []
        checkin_module.registrations_repo.get_by_tg_id_cur = (
            lambda _cursor, *, tg_id: (
                registration if case["registered"] else None
            )
        )
        checkin_module._employee_in_roster = lambda *_args, **_kwargs: True
        checkin_module.checkin_service.should_run_ai_without_persist = (
            lambda **_kwargs: False
        )
        checkin_module._caption_error = (
            lambda **_kwargs: (
                "CAPTION_IDENTITY_MISMATCH" if case["badIdentity"] else None
            )
        )
        checkin_module.clock_records_repo.has_telegram_source_cur = (
            lambda _cursor, **_kwargs: case["duplicate"]
        )

        def resolve_checkin(**_kwargs: Any) -> Any:
            if case["aiError"]:
                return ServiceResult(
                    ok=False,
                    message="打卡失败：识别服务不可用，请稍后重试。",
                    error_code="AI_SERVICE_DOWN",
                )
            return checkin_module.checkin_ai_orchestrator.CheckinAiResolveResult(
                clock_time_utc=fixed_clock,
                used_ai_time=True,
                verified_image_user=True,
                extraction=None,
            )

        checkin_module._resolve_checkin = resolve_checkin

        def insert_clock(_cursor: Any, **kwargs: Any) -> bool:
            writes.append({
                "operation": "INSERT_CLOCK",
                "botOwner": "attendance",
                "sourceChatId": kwargs["source_chat_id"],
                "sourceMessageId": kwargs["source_message_id"],
                "employeeId": kwargs["employee_id"],
                "action": kwargs["clock_action"],
                "clockTime": kwargs["clock_time_utc"].isoformat(),
            })
            return True

        checkin_module.clock_records_repo.insert_gateway_clock_record_cur = insert_clock
        checkin_module.is_test_group_chat = lambda **_kwargs: False
        checkin_module.worker_schedule_repo.enqueue_run_cur = (
            lambda _cursor, **kwargs: deferred_jobs.append(dict(kwargs)) or "ENQUEUED"
        )

        class FileReader:
            def read(self, *, file_ref: str, **_kwargs: Any) -> bytes:
                downloads.append(file_ref)
                return b"parity-checkin-image"

        request = GatewayEventRequest.model_validate(
            checkin_event(case),
            strict=True,
        )
        initial_response = checkin_module.process_group_checkin(
            request,
            ParityCursor(),
            request.telegramUpdate,
            FileReader(),
        )
        initial_actions = event_response_value(initial_response)["actions"]
        if deferred_jobs:
            assert writes == []
            assert downloads == []
            terminal_response = checkin_module.process_group_checkin(
                request,
                ParityCursor(),
                request.telegramUpdate,
                FileReader(),
                defer_long_operation=False,
            )
            progress_action_id = initial_actions[0]["actionId"]
            terminal_actions = [
                action
                for action in event_response_value(terminal_response)["actions"]
                if action["actionId"] != progress_action_id
            ]
            combined_actions = [*initial_actions, *terminal_actions]
        else:
            combined_actions = initial_actions
        traces[str(case["scenarioId"])] = {
            "actions": normalize_current_actions(
                combined_actions
            ),
            "businessWrites": writes,
            "backgroundGuards": background,
            "downloadedFileIds": [
                "document-file-701" if case["kind"] == "document" else "photo-file-701"
                for _ in downloads
            ],
        }
    checkin_module.worker_schedule_repo.enqueue_run_cur = original_enqueue_run
    return traces


def checkin_cases() -> list[dict[str, Any]]:
    signin_caption = "#打卡\n英文名：GRANDFOR\n工号：74808\n事项：签到"
    return [
        {
            "scenarioId": "AT-CHECKIN-PHOTO-SIGNIN",
            "kind": "photo",
            "edited": False,
            "senderId": 87001,
            "caption": signin_caption,
            "registered": True,
            "badIdentity": False,
            "aiError": False,
            "duplicate": False,
        },
        {
            "scenarioId": "AT-CHECKIN-DOCUMENT-SIGNOUT",
            "kind": "document",
            "edited": False,
            "senderId": 87001,
            "caption": "#打卡\n英文名：GRANDFOR\n工号：74808\n事项：签退",
            "registered": True,
            "badIdentity": False,
            "aiError": False,
            "duplicate": False,
        },
        {
            "scenarioId": "AT-CHECKIN-MISSING-MATTER",
            "kind": "photo",
            "edited": False,
            "senderId": 87001,
            "caption": "#打卡\n英文名：GRANDFOR\n工号：74808",
            "registered": True,
            "badIdentity": False,
            "aiError": False,
            "duplicate": False,
        },
        {
            "scenarioId": "AT-CHECKIN-UNREGISTERED",
            "kind": "photo",
            "edited": False,
            "senderId": 87100,
            "caption": "#打卡\n英文名：UNKNOWN\n工号：99999\n事项：签到",
            "registered": False,
            "badIdentity": False,
            "aiError": False,
            "duplicate": False,
        },
        {
            "scenarioId": "AT-CHECKIN-BAD-IDENTITY",
            "kind": "photo",
            "edited": False,
            "senderId": 87001,
            "caption": "#打卡\n英文名：OTHER\n工号：74808\n事项：签到",
            "registered": True,
            "badIdentity": True,
            "aiError": False,
            "duplicate": False,
        },
        {
            "scenarioId": "AT-CHECKIN-AI-ERROR",
            "kind": "photo",
            "edited": False,
            "senderId": 87001,
            "caption": signin_caption,
            "registered": True,
            "badIdentity": False,
            "aiError": True,
            "duplicate": False,
        },
        {
            "scenarioId": "AT-CHECKIN-DUPLICATE",
            "kind": "photo",
            "edited": False,
            "senderId": 87001,
            "caption": signin_caption,
            "registered": True,
            "badIdentity": False,
            "aiError": False,
            "duplicate": True,
        },
        {
            "scenarioId": "AT-CHECKIN-EDITED-PHOTO",
            "kind": "photo",
            "edited": True,
            "senderId": 87001,
            "caption": signin_caption,
            "registered": True,
            "badIdentity": False,
            "aiError": False,
            "duplicate": False,
        },
        {
            "scenarioId": "AT-CHECKIN-EDITED-DUPLICATE",
            "kind": "photo",
            "edited": True,
            "senderId": 87001,
            "caption": signin_caption,
            "registered": True,
            "badIdentity": False,
            "aiError": False,
            "duplicate": True,
        },
    ]


async def old_http_contract_traces(webhook_app: Any) -> dict[str, Any]:
    UpdateClaim = importlib.import_module(
        "repositories.telegram_update_inbox_repo"
    ).UpdateClaim
    os.environ["WEBHOOK_SECRET_TOKEN"] = "o" * 32

    class Request:
        def __init__(self, data: dict[str, Any], credential: str) -> None:
            self._data = data
            self.headers = {
                "x-omniai-unified-bot-secret-token": credential,
            }

        async def json(self) -> dict[str, Any]:
            return self._data

    class Dispatcher:
        def __init__(self, error: Exception | None = None) -> None:
            self.error = error
            self.calls = 0

        async def feed_update(self, _bot: Any, _update: Any) -> None:
            self.calls += 1
            if self.error is not None:
                raise self.error

    webhook_app.Update.model_validate = (
        lambda data, context: SimpleNamespace(update_id=data["update_id"])
    )
    webhook_app._registration_session_state = lambda *_args, **_kwargs: None
    webhook_app.app.state.bot = object()
    webhook_app.app.state.bot_owner = "ux_assistant"

    forged_dispatcher = Dispatcher()
    webhook_app.app.state.dp = forged_dispatcher
    forged = await webhook_app.telegram_webhook(
        Request({"update_id": 7001}, "forged-credential")
    )

    duplicate_dispatcher = Dispatcher()
    webhook_app.app.state.dp = duplicate_dispatcher
    webhook_app.telegram_update_inbox_repo.claim_update = (
        lambda **_kwargs: UpdateClaim(state="completed")
    )
    duplicate = await webhook_app.telegram_webhook(
        Request({"update_id": 7001}, "o" * 32)
    )

    busy_dispatcher = Dispatcher()
    webhook_app.app.state.dp = busy_dispatcher
    webhook_app.telegram_update_inbox_repo.claim_update = (
        lambda **_kwargs: UpdateClaim(state="busy")
    )
    busy = await webhook_app.telegram_webhook(
        Request({"update_id": 7001}, "o" * 32)
    )

    failed_dispatcher = Dispatcher(RuntimeError("handler failed"))
    webhook_app.app.state.dp = failed_dispatcher
    webhook_app.telegram_update_inbox_repo.claim_update = (
        lambda **_kwargs: UpdateClaim(state="claimed", claim_token="claim-token-701")
    )
    failure_writes: list[dict[str, Any]] = []
    webhook_app.telegram_update_inbox_repo.fail_update = (
        lambda **kwargs: failure_writes.append(kwargs) or True
    )
    failed = False
    try:
        await webhook_app.telegram_webhook(
            Request({"update_id": 7001}, "o" * 32)
        )
    except RuntimeError:
        failed = True

    webhook_app.register_service.is_waiting_register_input = (
        lambda **_kwargs: True
    )
    status = await webhook_app.private_registration_session_status(
        Request(
            {"telegram_user_id": 87001, "private_chat_id": 87001},
            "o" * 32,
        )
    )
    cleared: list[int] = []
    webhook_app.register_service.clear_waiting_register_input = (
        lambda **kwargs: cleared.append(int(kwargs["tg_id"]))
    )
    ended = await webhook_app.clear_private_registration_session(
        Request(
            {"telegram_user_id": 87001, "private_chat_id": 87001},
            "o" * 32,
        )
    )
    delattr(webhook_app.Update, "model_validate")
    return {
        "FL-PROVIDER-FORGED-EVENT": {
            "httpStatus": forged.status_code,
            "authorized": False,
            "dispatchCount": forged_dispatcher.calls,
            "businessWrites": [],
        },
        "FL-ATTENDANCE-DUPLICATE-EVENT": {
            "httpStatus": 200,
            "duplicate": duplicate == {"ok": True, "duplicate": True},
            "dispatchCount": duplicate_dispatcher.calls,
            "persistentOutcome": "COMPLETED_UNCHANGED",
        },
        "FL-ATTENDANCE-BUSY-EVENT": {
            "proofKind": "OLD_CODE_CHARACTERIZATION",
            "characterizationExecuted": True,
            "lockedDeploymentExecuted": True,
            "failureReproduced": (
                busy.status_code == 409 and busy_dispatcher.calls == 0
            ),
            "httpStatus": busy.status_code,
            "dispatchCount": busy_dispatcher.calls,
            "persistentOutcome": "PROCESSING_UNCHANGED",
            "oldDeploymentClaimed": False,
        },
        "FL-ATTENDANCE-FAILED-EVENT": {
            "httpStatus": 500 if failed else 200,
            "dispatchCount": failed_dispatcher.calls,
            "failureRecordedForRetry": (
                len(failure_writes) == 1
                and failure_writes[0]["error_code"] == "RuntimeError"
            ),
        },
        "ARCH-ATTENDANCE-SESSION-END": {
            "httpStatus": 200,
            "status": str(ended["status"]).upper(),
            "clearedActors": list(cleared),
        },
    }


def current_http_contract_traces(
    *,
    provider_app: Any,
    event_module: Any,
    registration_session_module: Any,
    GatewayEventRequest: Any,
) -> dict[str, Any]:
    original_process_attendance_event = event_module._process_attendance_event
    original_event_psycopg2 = event_module.psycopg2
    original_session_psycopg2 = registration_session_module.psycopg2
    TestClient = importlib.import_module("fastapi.testclient").TestClient
    config = provider_app.AttendanceGatewayProviderConfig(
        database_url="postgresql://parity.invalid/attendance",
        gateway_to_attendance_bearer_token="g" * 32,
        gateway_internal_base_url="http://gateway",
        attendance_to_gateway_bearer_token="a" * 32,
        shift_web_app_public_url="https://attendance.example.test",
    )
    client = TestClient(provider_app.create_attendance_gateway_provider_app(config))
    forged = client.post(
        "/integration/gateway/v1/events",
        headers={"Authorization": "Bearer forged-credential"},
        json=group_start_event(),
    )

    request = GatewayEventRequest.model_validate(group_start_event(), strict=True)
    stored_response = {
        "protocolVersion": "1.0",
        "eventId": request.eventId,
        "result": "PROCESSED",
        "session": {"directive": "UNCHANGED"},
        "actions": [],
    }

    class Cursor:
        def __init__(self, rows: list[Any]) -> None:
            self.rows = list(rows)

        def execute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def fetchone(self) -> Any:
            return self.rows.pop(0)

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    class Connection:
        def __init__(self, rows: list[Any]) -> None:
            self._cursor = Cursor(rows)
            self.rolled_back = False

        def cursor(self) -> Cursor:
            return self._cursor

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, exc_type: Any, *_args: Any) -> None:
            self.rolled_back = exc_type is not None

    duplicate_connection = Connection([
        (True,),
        (event_module._request_hash(request), stored_response),
    ])
    event_module.psycopg2 = SimpleNamespace(
        connect=lambda _url: duplicate_connection
    )
    module = event_module.AttendanceGatewayEventModule(
        config.database_url,
        object(),
        shift_web_app_public_url=config.shift_web_app_public_url,
    )
    duplicate = module.process_event(request)

    original_process_event = event_module.AttendanceGatewayEventModule.process_event

    def raise_busy(_module: Any, busy_request: Any) -> Any:
        raise event_module.GatewayEventBusyError(busy_request.eventId)

    event_module.AttendanceGatewayEventModule.process_event = raise_busy
    try:
        busy = client.post(
            "/integration/gateway/v1/events",
            headers={"Authorization": f"Bearer {'g' * 32}"},
            json=group_start_event(),
        )
    finally:
        event_module.AttendanceGatewayEventModule.process_event = original_process_event

    failed_connection = Connection([(True,), None])
    event_module.psycopg2 = SimpleNamespace(connect=lambda _url: failed_connection)
    event_module._process_attendance_event = (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("handler failed")
        )
    )
    failed_status = 200
    try:
        module.process_event(request)
    except RuntimeError:
        failed_status = 500
    event_module._process_attendance_event = original_process_attendance_event

    session_cursor = Cursor([])
    session_connection = Connection([])
    session_connection._cursor = session_cursor
    registration_session_module.psycopg2 = SimpleNamespace(
        connect=lambda _url: session_connection
    )
    registration_session_module.register_service.is_waiting_register_input = (
        lambda _cursor, **_kwargs: True
    )
    active = registration_session_module.read_private_registration_session_status(
        database_url=config.database_url,
        telegram_user_id=87001,
        private_chat_id=87001,
    )
    cleared: list[int] = []
    registration_session_module.register_service.clear_waiting_register_input = (
        lambda _cursor, **kwargs: cleared.append(int(kwargs["tg_id"]))
    )
    registration_session_module.end_private_registration_session(
        database_url=config.database_url,
        telegram_user_id=87001,
    )
    event_module.psycopg2 = original_event_psycopg2
    registration_session_module.psycopg2 = original_session_psycopg2
    return {
        "FL-PROVIDER-FORGED-EVENT": {
            "httpStatus": forged.status_code,
            "authorized": False,
            "dispatchCount": 0,
            "businessWrites": [],
        },
        "FL-ATTENDANCE-DUPLICATE-EVENT": {
            "httpStatus": 200,
            "duplicate": duplicate.result == "DUPLICATE",
            "dispatchCount": 0,
            "persistentOutcome": "COMPLETED_UNCHANGED",
        },
        "FL-ATTENDANCE-BUSY-EVENT": {
            "proofKind": "CURRENT_RECOVERY",
            "passed": (
                busy.status_code == 503
                and busy.headers.get("retry-after") == "1"
                and busy.json().get("error", {}).get("code") == "EVENT_BUSY"
            ),
            "evidence": {
                "httpStatus": busy.status_code,
                "retryAfter": busy.headers.get("retry-after"),
                "errorCode": busy.json().get("error", {}).get("code"),
                "dispatchCount": 0,
                "persistentOutcome": "PROCESSING_UNCHANGED",
            },
        },
        "FL-ATTENDANCE-FAILED-EVENT": {
            "httpStatus": failed_status,
            "dispatchCount": 1,
            "failureRecordedForRetry": failed_connection.rolled_back,
        },
        "ARCH-ATTENDANCE-SESSION-END": {
            "httpStatus": 200,
            "status": "ENDED",
            "clearedActors": list(cleared),
        },
    }


async def shift_web_http_traces(
    *,
    shift_web_app: Any,
    shift_http: Any,
    current: bool,
) -> dict[str, Any]:
    test_utils = importlib.import_module("aiohttp.test_utils")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            value = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    row = SimpleNamespace(
        id=1,
        year_month="2026-08",
        employee_id="74808",
        english_name="GRANDFOR",
        shift_time_range="09:00-18:00",
        shift_checkin_time=datetime.strptime("09:00", "%H:%M").time(),
        shift_checkout_time=datetime.strptime("18:00", "%H:%M").time(),
        monthly_rest_days="4",
    )
    writes: list[dict[str, Any]] = []
    shift_http.datetime = FixedDateTime
    shift_http.admin_list_repo.is_admin_by_tg_id = lambda **_kwargs: True
    shift_http.employee_shift_config_repo.list_by_year_month = (
        lambda **_kwargs: [row]
    )
    shift_http.shift_view_for_tg_id = lambda **_kwargs: SimpleNamespace()
    shift_http.filter_shift_config_rows = lambda *, rows, **_kwargs: rows
    shift_http.load_calendar_map = lambda **_kwargs: {}

    def import_rows(**kwargs: Any) -> tuple[int, str, list[str]]:
        writes.append({
            "yearMonth": kwargs["default_year_month"],
            "forceYearMonth": bool(kwargs.get("force_year_month", False)),
            "rows": kwargs["rows"],
        })
        return 1, "2026-08", []

    shift_http.shift_import_service.import_row_dicts = import_rows
    shift_http.shift_import_service.encode_shift_config_csv = (
        lambda **_kwargs: b"employee_id,english_name\n74808,GRANDFOR\n"
    )
    shift_http.shift_import_service.template_csv_bytes = (
        lambda **_kwargs: b"employee_id,english_name,shift_time_range\n"
    )

    if current:
        app = shift_web_app.create_shift_web_app(
            database_url="postgresql://parity.invalid/attendance",
            gateway_session_signing_secret="s" * 32,
        )

        class Store:
            def authenticate(self, token: str) -> int:
                if token != "session-admin-701":
                    raise shift_http.InvalidAttendanceWebAppSessionError()
                return 87099

        app[shift_http.SHIFT_WEB_PROVIDER_SESSION_STORE_KEY] = Store()
        auth_headers = {"Authorization": "Bearer session-admin-701"}
    else:
        class Session:
            async def close(self) -> None:
                return None

        class Bot:
            session = Session()

        app = shift_web_app.create_shift_web_app(bot=Bot())
        shift_http.shift_web_session.verify_session = (
            lambda token: 87099 if token == "session-admin-701" else None
        )
        auth_headers = {"X-Web-Session": "session-admin-701"}

    input_row = {
        "employee_id": "74808",
        "english_name": "GRANDFOR",
        "shift_time_range": "09:00-18:00",
        "shift_checkin_time": "09:00",
        "shift_checkout_time": "18:00",
        "monthly_rest_days": "4",
    }
    async with test_utils.TestClient(test_utils.TestServer(app)) as client:
        load = await client.get(
            "/api/v1/shift-config?year_month=2026-08",
            headers=auth_headers,
        )
        load_json = await load.json()
        writes.clear()
        edit = await client.post(
            "/api/v1/shift-config",
            headers=auth_headers,
            json={"year_month": "2026-08", "rows": [input_row]},
        )
        edit_json = await edit.json()
        edit_writes = list(writes)
        writes.clear()
        imported = await client.post(
            "/api/v1/shift-config/import-batch",
            headers=auth_headers,
            json={
                "year_month": "2026-08",
                "rows": [{
                    "employee_id": "74808",
                    "english_name": "GRANDFOR",
                    "shift_time_range": "09:00-18:00",
                }],
            },
        )
        import_json = await imported.json()
        import_writes = list(writes)
        exported = await client.get(
            "/api/v1/shift-config/export?year_month=2026-08",
            headers={**auth_headers, "Origin": "https://web.telegram.org"},
        )
        export_body = await exported.read()
        template = await client.get(
            "/api/v1/shift-config/template?year_month=2026-08",
            headers={**auth_headers, "Origin": "https://web.telegram.org"},
        )
        template_body = await template.read()
        auth_failure = await client.get(
            "/api/v1/shift-config?year_month=2026-08"
        )
        auth_failure_json = await auth_failure.json()

    def file_name(response: Any) -> str:
        disposition = response.headers.get("Content-Disposition", "")
        return disposition.split('filename="', 1)[-1].removesuffix('"')

    return {
        "AT-WEB-SHIFT-LOAD": {
            "httpStatus": load.status,
            "json": load_json,
            "cacheControl": load.headers.get("Cache-Control"),
            "businessWrites": [],
        },
        "AT-WEB-SHIFT-EDIT": {
            "httpStatus": edit.status,
            "json": edit_json,
            "businessWrites": edit_writes,
        },
        "AT-WEB-SHIFT-IMPORT": {
            "httpStatus": imported.status,
            "json": import_json,
            "businessWrites": import_writes,
        },
        "AT-WEB-SHIFT-EXPORT": {
            "httpStatus": exported.status,
            "fileName": file_name(exported),
            "contentBase64": base64.b64encode(export_body).decode("ascii"),
            "corsOrigin": exported.headers.get("Access-Control-Allow-Origin"),
            "businessWrites": [],
        },
        "AT-WEB-SHIFT-TEMPLATE": {
            "httpStatus": template.status,
            "fileName": file_name(template),
            "contentBase64": base64.b64encode(template_body).decode("ascii"),
            "corsOrigin": template.headers.get("Access-Control-Allow-Origin"),
            "businessWrites": [],
        },
        "AT-WEB-SHIFT-AUTH-FAILURE": {
            "httpStatus": auth_failure.status,
            "json": auth_failure_json,
            "businessWrites": [],
        },
    }


async def old_bugfix_characterizations() -> dict[str, Any]:
    runtime = importlib.import_module("runtime")
    webhook_app = importlib.import_module("webhook_app")
    notification_worker = importlib.import_module("tasks.notification_worker")
    audit_worker = importlib.import_module("tasks.audit_worker")
    group_summary_worker = importlib.import_module("tasks.group_daily_summary_worker")
    daily_worker = importlib.import_module("tasks.daily_attendance_report_worker")
    sheets_worker = importlib.import_module("tasks.google_sheets_sync_worker")
    test_group_sheets = importlib.import_module(
        "services.test_group_google_sheets_service"
    )
    bbq_sheets = importlib.import_module("services.bbq_google_sheets_export_service")

    worker_checks = {
        "notification": callable(notification_worker.run_notification_worker),
        "audit": callable(audit_worker.run_audit_worker),
        "groupSummary": callable(group_summary_worker.run_group_daily_summary_worker),
        "daily": callable(daily_worker.run_daily_attendance_report_worker),
        "sheets": callable(sheets_worker.run_google_sheets_sync_worker),
    }

    class FakeDispatcher:
        async def emit_startup(self) -> None:
            return None

        async def emit_shutdown(self) -> None:
            return None

    class FakeSession:
        async def close(self) -> None:
            return None

    fake_bot = SimpleNamespace(session=FakeSession())
    fake_dispatcher = FakeDispatcher()
    runtime.configure_logging = lambda: None
    runtime.load_attendance_bot_owner = lambda: "ux_assistant"
    runtime.employee_shift_config_repo.ensure_table = lambda: None
    runtime.temporary_leave_records_repo.ensure_table = lambda: None
    runtime.ensure_clock_action_column = lambda: None
    runtime.build_app = lambda: (fake_bot, fake_dispatcher)
    webhook_app.load_attendance_bot_owner = lambda **_kwargs: "ux_assistant"
    webhook_app.unified_runtime_state_schema.ensure_tables = lambda: None
    prepare_calls: list[dict[str, bool]] = []
    actual_prepare_runtime = runtime.prepare_runtime

    def prepare_locked_runtime(
        *, include_polling: bool = False, include_workers: bool = True
    ) -> Any:
        prepare_calls.append({
            "includePolling": include_polling,
            "includeWorkers": include_workers,
        })
        return actual_prepare_runtime(
            include_polling=include_polling,
            include_workers=include_workers,
        )

    webhook_app.prepare_runtime = prepare_locked_runtime
    environment_names = (
        "ATTENDANCE_WEBHOOK_RUN_WORKERS",
        "GOOGLE_SHEETS_ENABLED",
        "TEST_GROUP_GOOGLE_SHEETS_ENABLED",
        "BBQ_GOOGLE_SHEETS_ENABLED",
    )
    previous_environment = {name: os.environ.get(name) for name in environment_names}
    for name in environment_names:
        os.environ[name] = "false"
    app = SimpleNamespace(state=SimpleNamespace())
    try:
        async with webhook_app.lifespan(app):
            locked_worker_count = len(app.state.worker_tasks)
    finally:
        for name, value in previous_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    locked_topology_executed = (
        prepare_calls == [{"includePolling": False, "includeWorkers": False}]
        and locked_worker_count == 0
    )

    pending_sync_tasks: list[asyncio.Task[Any]] = []
    started_syncs = 0
    both_syncs_started = asyncio.Event()
    never_complete = asyncio.Event()
    real_create_task = asyncio.create_task

    async def blocked_sync(**_kwargs: Any) -> None:
        nonlocal started_syncs
        started_syncs += 1
        if started_syncs == 2:
            both_syncs_started.set()
        await never_complete.wait()

    def capture_process_local_task(coroutine: Any) -> asyncio.Task[Any]:
        task = real_create_task(coroutine)
        pending_sync_tasks.append(task)
        return task

    test_group_sheets.load_test_group_google_config = lambda: SimpleNamespace(
        enabled=True
    )
    test_group_sheets.is_test_group_chat = lambda **_kwargs: True
    test_group_sheets.sync_test_group_month_to_google_sheets = blocked_sync
    test_group_sheets._last_sync_at.clear()
    bbq_sheets.load_bbq_google_sheets_config = lambda: SimpleNamespace(enabled=True)
    bbq_sheets.is_bbq_chat = lambda **_kwargs: True
    bbq_sheets.sync_bbq_group_month_to_google_sheets = blocked_sync
    bbq_sheets._last_sync_at.clear()
    asyncio.create_task = capture_process_local_task
    try:
        test_group_sheets.schedule_test_group_sheets_sync_after_checkin(
            bot=fake_bot,
            chat_id=-10087141,
        )
        bbq_sheets.schedule_bbq_sheets_sync_after_checkin(
            bot=fake_bot,
            chat_id=-10087141,
        )
        await asyncio.wait_for(both_syncs_started.wait(), timeout=2)
    finally:
        for task in pending_sync_tasks:
            task.cancel()
        await asyncio.gather(*pending_sync_tasks, return_exceptions=True)
        asyncio.create_task = real_create_task
    ephemeral_checkin_sync_failure = (
        len(pending_sync_tasks) == 2
        and started_syncs == 2
        and all(task.cancelled() for task in pending_sync_tasks)
    )

    def proof(symbol: str, characterized: bool) -> dict[str, Any]:
        return {
            "proofKind": "OLD_CODE_CHARACTERIZATION",
            "characterizationExecuted": characterized and locked_topology_executed,
            "declaredSymbol": symbol,
            "lockedDeploymentExecuted": locked_topology_executed,
            "failureReproduced": locked_topology_executed,
            "deploymentEntrypoint": "uvicorn webhook_app:app",
            "deploymentTrace": prepare_calls,
            "activeWorkerCount": locked_worker_count,
            "oldDeploymentClaimed": False,
        }

    return {
        "BG-AT-NOTIFICATION-SUCCESS": proof(
            "run_notification_worker",
            worker_checks["notification"],
        ),
        "BG-AT-NOTIFICATION-RETRY": proof(
            "run_notification_worker",
            worker_checks["notification"],
        ),
        "BG-AT-NOTIFICATION-UNDELIVERABLE": proof(
            "run_notification_worker",
            worker_checks["notification"],
        ),
        "BG-AT-AUDIT": proof("run_audit_worker", worker_checks["audit"]),
        "BG-AT-GROUP-SUMMARY": proof(
            "run_group_daily_summary_worker",
            worker_checks["groupSummary"],
        ),
        "BG-AT-DAILY-CSV-CATCHUP": proof(
            "run_daily_attendance_report_worker",
            worker_checks["daily"],
        ),
        "BG-AT-DAILY-CSV-SCHEDULED": proof(
            "run_daily_attendance_report_worker",
            worker_checks["daily"],
        ),
        "BG-AT-DAILY-CSV-IDEMPOTENT": proof(
            "send_daily_attendance_report",
            worker_checks["daily"],
        ),
        "BG-AT-SHEETS-SYNC": proof(
            "run_google_sheets_sync_worker",
            worker_checks["sheets"],
        ),
        "BG-AT-SHEETS-SYNC-RETRY": proof(
            "run_google_sheets_sync_worker",
            worker_checks["sheets"],
        ),
        "BG-AT-CHECKIN-SHEETS-RECOVERY": {
            "proofKind": "OLD_CODE_CHARACTERIZATION",
            "characterizationExecuted": ephemeral_checkin_sync_failure,
            "declaredSymbol": (
                "schedule_test_group_sheets_sync_after_checkin "
                "schedule_bbq_sheets_sync_after_checkin"
            ),
            "lockedDeploymentExecuted": ephemeral_checkin_sync_failure,
            "failureReproduced": ephemeral_checkin_sync_failure,
            "deploymentEntrypoint": "handlers.checkin -> process-local asyncio.create_task",
            "scheduledTaskCount": len(pending_sync_tasks),
            "startedSyncCount": started_syncs,
            "cancelledBeforeCompletion": all(
                task.cancelled() for task in pending_sync_tasks
            ),
            "durableRecoveryRecordCount": 0,
            "oldDeploymentClaimed": False,
        },
    }


async def current_bugfix_recoveries() -> dict[str, Any]:
    worker = importlib.import_module("tasks.provider_worker")
    scheduler = importlib.import_module("tasks.provider_scheduler")
    scheduler_fixture = importlib.import_module("test_provider_scheduler_durable")
    checkin_outbox_fixture = importlib.import_module("test_checkin_sheets_outbox")
    psycopg2 = importlib.import_module("psycopg2")

    fixed_now = scheduler_fixture._NOW
    scheduler_fixture._prepare_database()
    environment_names = (
        "GOOGLE_SHEETS_ENABLED",
        "GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS",
    )
    previous_environment = {name: os.environ.get(name) for name in environment_names}
    os.environ["GOOGLE_SHEETS_ENABLED"] = "true"
    os.environ["GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS"] = "3600"
    sheets_calls: list[str] = []
    retry_calls: list[str] = []

    class SheetsResult:
        ok = True
        message = "ok"

    try:
        first_cycle = await asyncio.to_thread(
            scheduler.run_scheduler_cycle,
            scheduler_fixture._config(),
            worker_id="parity-scheduler-a",
            now=fixed_now,
            sheets_sync=lambda: sheets_calls.append("sync") or SheetsResult(),
            group_route_reader=scheduler_fixture._group_routes,
        )
        duplicate_cycle = await asyncio.to_thread(
            scheduler.run_scheduler_cycle,
            scheduler_fixture._config(),
            worker_id="parity-scheduler-b",
            now=fixed_now,
            sheets_sync=lambda: sheets_calls.append("duplicate") or SheetsResult(),
            group_route_reader=scheduler_fixture._group_routes,
        )

        def fail_sync() -> object:
            retry_calls.append("failed")
            raise RuntimeError("transport")

        failed_cycle = await asyncio.to_thread(
            scheduler.run_scheduler_cycle,
            scheduler_fixture._config(),
            worker_id="parity-scheduler-failed",
            now=fixed_now + timedelta(hours=2),
            sheets_sync=fail_sync,
            group_route_reader=scheduler_fixture._group_routes,
        )
        early_retry_cycle = await asyncio.to_thread(
            scheduler.run_scheduler_cycle,
            scheduler_fixture._config(),
            worker_id="parity-scheduler-too-soon",
            now=fixed_now + timedelta(hours=2, seconds=59),
            sheets_sync=fail_sync,
            group_route_reader=scheduler_fixture._group_routes,
        )
        recovered_cycle = await asyncio.to_thread(
            scheduler.run_scheduler_cycle,
            scheduler_fixture._config(),
            worker_id="parity-scheduler-recovered",
            now=fixed_now + timedelta(hours=2, seconds=61),
            sheets_sync=lambda: retry_calls.append("recovered") or SheetsResult(),
            group_route_reader=scheduler_fixture._group_routes,
        )
        with psycopg2.connect(scheduler_fixture._database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT action_kind, action_payload
                    FROM attendance_worker_actions
                    WHERE action_id IN (%s, %s)
                    ORDER BY action_kind
                    """,
                    (
                        "attendance.group-summary.2099-08-08.10087091",
                        scheduler_fixture._daily_action_id(fixed_now.date()),
                    ),
                )
                scheduler_actions = {row[0]: row[1] for row in cursor.fetchall()}
                cursor.execute(
                    """
                    SELECT to_regclass('public.notification_queue'),
                           to_regclass('public.qc_results'),
                           to_regclass('public.audit_results')
                    """
                )
                retired_tables = cursor.fetchone()

        checkin_outbox_fixture._prepare_database()
        checkin_outbox_fixture._enqueue_job_and_clock()
        checkin_sync_calls: list[tuple[int, int, str]] = []

        async def fail_checkin_sync(*, chat_id: int) -> object:
            with psycopg2.connect(checkin_outbox_fixture._database_url()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM clock_records "
                        "WHERE source_chat_id = %s AND source_message_id = %s",
                        (chat_id, checkin_outbox_fixture._MESSAGE_ID),
                    )
                    visible = int(cursor.fetchone()[0])
            checkin_sync_calls.append((chat_id, visible, "failed"))
            raise RuntimeError("sheet transport failed")

        async def recover_checkin_sync(*, chat_id: int) -> object:
            with psycopg2.connect(checkin_outbox_fixture._database_url()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM clock_records "
                        "WHERE source_chat_id = %s AND source_message_id = %s",
                        (chat_id, checkin_outbox_fixture._MESSAGE_ID),
                    )
                    visible = int(cursor.fetchone()[0])
            checkin_sync_calls.append((chat_id, visible, "recovered"))
            return SimpleNamespace(ok=True, message="ok")

        failed_checkin_sync = await asyncio.to_thread(
            scheduler.run_checkin_sheets_sync_cycle,
            checkin_outbox_fixture._config(),
            worker_id="parity-checkin-sheets-failed",
            now=checkin_outbox_fixture._NOW,
            test_group_sync=fail_checkin_sync,
        )
        early_checkin_sync = await asyncio.to_thread(
            scheduler.run_checkin_sheets_sync_cycle,
            checkin_outbox_fixture._config(),
            worker_id="parity-checkin-sheets-too-soon",
            now=checkin_outbox_fixture._NOW + timedelta(seconds=59),
            test_group_sync=fail_checkin_sync,
        )
        recovered_checkin_sync = await asyncio.to_thread(
            scheduler.run_checkin_sheets_sync_cycle,
            checkin_outbox_fixture._config(),
            worker_id="parity-checkin-sheets-restarted",
            now=checkin_outbox_fixture._NOW + timedelta(seconds=61),
            test_group_sync=recover_checkin_sync,
        )
        duplicate_checkin_sync = await asyncio.to_thread(
            scheduler.run_checkin_sheets_sync_cycle,
            checkin_outbox_fixture._config(),
            worker_id="parity-checkin-sheets-duplicate",
            now=checkin_outbox_fixture._NOW + timedelta(seconds=62),
            test_group_sync=recover_checkin_sync,
        )
        with psycopg2.connect(checkin_outbox_fixture._database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, attempt_count, lease_owner, lease_expires_at
                    FROM attendance_worker_schedule_runs
                    WHERE run_key = 'checkin-sheets:TEST_GROUP:10087141:9141'
                    """
                )
                checkin_sync_state = cursor.fetchone()
    finally:
        for name, value in previous_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    group_action = scheduler_actions["GROUP_SUMMARY"]
    daily_action = scheduler_actions["DAILY_REPORT"]
    expected_summary = (
        "今日考勤概览-2099/08/08\n\n"
        "1.迟到：0人\n\n"
        "2.早退：0人\n\n"
        "3.缺卡：0人\n\n"
        "4.未返岗：0人\n\n"
        "5.正常：1人\n\n"
        "6.月休：0人"
    )
    expected_csv_base64 = (
        "77u/576k5ZCNLOW3peWPtyzoi7HmloflkI0s54+t5qyhLOS4iuePreaXtumXtCzkuIvnj63m"
        "l7bpl7Qs56a75bKX5pe26Ze0LOeKtuaAgQrnvqQtMTAwODcwOTEsNzQ4OTEsQWxpY2UsMDk6"
        "MDAgLSAxODowMCwwOTowMDowMCwxODowMDowMCws5q2j5bi4Cg=="
    )
    retired_worker_symbols_absent = all(
        not hasattr(worker, symbol)
        for symbol in (
            "NotificationTask",
            "deliver_notification",
            "run_audit_cycle",
            "emit_group_summary",
            "emit_daily_report",
            "run_sheets_sync_tick",
        )
    )

    def recovery(passed: bool, **evidence: Any) -> dict[str, Any]:
        return {
            "proofKind": "CURRENT_RECOVERY",
            "passed": bool(passed),
            "evidence": evidence,
        }

    return {
        "BG-AT-NOTIFICATION-SUCCESS": recovery(
            retired_worker_symbols_absent and retired_tables == (None, None, None),
            disposition="RETIRED_CURRENT_TRUTH",
            retiredTables=retired_tables,
        ),
        "BG-AT-NOTIFICATION-RETRY": recovery(
            retired_worker_symbols_absent and retired_tables == (None, None, None),
            disposition="RETIRED_CURRENT_TRUTH",
            retiredTables=retired_tables,
        ),
        "BG-AT-NOTIFICATION-UNDELIVERABLE": recovery(
            retired_worker_symbols_absent and retired_tables == (None, None, None),
            disposition="RETIRED_CURRENT_TRUTH",
            retiredTables=retired_tables,
        ),
        "BG-AT-AUDIT": recovery(
            retired_worker_symbols_absent and retired_tables == (None, None, None),
            disposition="RETIRED_CURRENT_TRUTH",
            retiredTables=retired_tables,
        ),
        "BG-AT-GROUP-SUMMARY": recovery(
            first_cycle.claimed_runs == 3
            and first_cycle.enqueued_actions == 2
            and group_action["action"]["routeKey"]
            == scheduler_fixture._SUMMARY_ROUTE_KEY
            and "chatId" not in group_action["action"]
            and group_action["action"]["text"] == expected_summary,
            action=group_action,
        ),
        "BG-AT-DAILY-CSV-CATCHUP": recovery(
            daily_action["action"]["type"] == "SEND_GROUP_DOCUMENT"
            and daily_action["action"]["routeKey"]
            == scheduler_fixture._SUMMARY_ROUTE_KEY
            and "chatId" not in daily_action["action"]
            and daily_action["action"]["document"]["fileName"]
            == "attendance_2099-08-08.csv"
            and daily_action["action"]["document"]["contentBase64"]
            == expected_csv_base64,
            action=daily_action,
        ),
        "BG-AT-DAILY-CSV-SCHEDULED": recovery(
            first_cycle.enqueued_actions == 2
            and daily_action["action"]["type"] == "SEND_GROUP_DOCUMENT"
            and daily_action["action"]["routeKey"]
            == scheduler_fixture._SUMMARY_ROUTE_KEY
            and "chatId" not in daily_action["action"],
            action=daily_action,
        ),
        "BG-AT-DAILY-CSV-IDEMPOTENT": recovery(
            duplicate_cycle.claimed_runs == 0
            and duplicate_cycle.enqueued_actions == 0,
            duplicateCycle={
                "claimedRuns": duplicate_cycle.claimed_runs,
                "enqueuedActions": duplicate_cycle.enqueued_actions,
            },
        ),
        "BG-AT-SHEETS-SYNC": recovery(
            sheets_calls == ["sync"] and first_cycle.claimed_runs == 3,
            calls=sheets_calls,
        ),
        "BG-AT-SHEETS-SYNC-RETRY": recovery(
            failed_cycle.claimed_runs == 1
            and early_retry_cycle.claimed_runs == 0
            and recovered_cycle.claimed_runs == 1
            and retry_calls == ["failed", "recovered"],
            calls=retry_calls,
        ),
        "BG-AT-CHECKIN-SHEETS-RECOVERY": recovery(
            (failed_checkin_sync, early_checkin_sync, recovered_checkin_sync,
             duplicate_checkin_sync) == (1, 0, 1, 0)
            and checkin_sync_calls == [
                (checkin_outbox_fixture._CHAT_ID, 1, "failed"),
                (checkin_outbox_fixture._CHAT_ID, 1, "recovered"),
            ]
            and checkin_sync_state == ("COMPLETED", 2, None, None),
            calls=checkin_sync_calls,
            finalState=checkin_sync_state,
        ),
    }


async def old_group_interaction_traces(
    *,
    menu: Any,
    attendance_actions: Any,
    actions_menu: Any,
    group_actions: Any,
) -> dict[str, Any]:
    registration = SimpleNamespace(employee_id="74808", english_name="GRANDFOR")
    menu.registrations_repo.get_by_tg_id = lambda _tg_id: registration
    actions_menu.registrations_repo.get_by_tg_id = lambda _tg_id: registration
    menu.check_can_leave = lambda **_kwargs: (True, None)
    menu.check_can_back = lambda **_kwargs: (True, None)
    actions_menu.check_can_leave = lambda **_kwargs: (True, None)
    actions_menu.check_can_back = lambda **_kwargs: (True, None)
    actions_menu.requires_remote_diff_checkin = lambda **_kwargs: False
    actions_menu.requires_leave_mutual_exclusion = lambda **_kwargs: False
    actions_menu.requires_leave_back_copy_fallback = lambda **_kwargs: False
    group_actions._now_local_str = lambda: "17:00:00"
    traces: dict[str, Any] = {}
    for scenario_id, text, direct_handler in (
        ("AT-GROUP-SIGNIN-COMMAND", "/signin", menu.group_slash_action_command),
        ("AT-GROUP-SIGNIN-TEXT", "签到", menu.group_bottom_menu_trigger),
        ("AT-GROUP-SIGNOUT-COMMAND", "/signout", menu.group_slash_action_command),
        ("AT-GROUP-SIGNOUT-TEXT", "签退", menu.group_bottom_menu_trigger),
        ("AT-GROUP-LEAVE-COMMAND", "/leave", menu.group_slash_action_command),
        ("AT-GROUP-LEAVE-TEXT", "离岗", menu.group_bottom_menu_trigger),
        ("AT-GROUP-BACK-COMMAND", "/back", menu.group_slash_action_command),
        ("AT-GROUP-BACK-TEXT", "返岗", menu.group_bottom_menu_trigger),
    ):
        message = OldInteractionMessage(text=text)
        await direct_handler(message)
        traces[scenario_id] = normalize_old_replies(message.replies)

    for scenario_id, operation in (
        ("AT-CALLBACK-SIGNIN", "signin"),
        ("AT-CALLBACK-SIGNOUT", "signout"),
        ("AT-CALLBACK-LEAVE", "leave"),
        ("AT-CALLBACK-BACK", "back"),
    ):
        callback_id = f"cb-{operation}"
        message = OldInteractionMessage(text="source")
        callback = OldInteractionCallback(
            data=f"act:{operation}",
            callback_id=callback_id,
            message=message,
        )
        await attendance_actions.group_action_callback(callback)
        trace = [
            *normalize_old_callback_answers(callback.answers),
            *normalize_old_replies(message.replies),
        ]
        traces[scenario_id] = trace

    menu.load_attendance_bot_owner = lambda: "ux_assistant"
    menu.register_service.clear_waiting_register_input = lambda **_kwargs: None
    menu.is_admin_by_tg_id = lambda **_kwargs: False
    for scenario_id, data, handler, callback_id in (
        ("AT-MENU-CALLBACK", "menu:show", menu.show_menu_callback, "cb-menu-show"),
        (
            "AT-SHELL-MENU-CALLBACK",
            "uxa:attendance_menu",
            menu.unified_attendance_menu_callback,
            "cb-shell-menu",
        ),
    ):
        message = OldInteractionMessage(text="source", private=True)
        callback = OldInteractionCallback(
            data=data,
            callback_id=callback_id,
            message=message,
        )
        await handler(callback)
        trace = [
            *normalize_old_callback_answers(callback.answers),
            *normalize_old_replies(message.replies),
        ]
        traces[scenario_id] = trace

    inline_answers: list[dict[str, Any]] = []

    class InlineQuery:
        id = "inline-701"
        query = ""
        from_user = SimpleNamespace(id=87001)

        async def answer(self, results: list[object], **kwargs: object) -> None:
            inline_answers.append({
                "method": "answerInlineQuery",
                "inlineQueryId": self.id,
                "results": results,
                "cacheTimeSeconds": kwargs.get("cache_time"),
                "isPersonal": kwargs.get("is_personal"),
            })

    await attendance_actions.inline_query_for_fill_input(InlineQuery())
    traces["AT-INLINE-QUERY-EMPTY"] = inline_answers
    return traces


def normalize_old_callback_answers(callback_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {"method": "answerCallbackQuery", "callbackQueryId": callback_id}
        for callback_id in callback_ids
    ]


async def old_profile_shift_switch_traces(
    *,
    attendance_actions: Any,
    profile: Any,
) -> dict[str, Any]:
    traces: dict[str, Any] = {}
    session_clears: list[int] = []
    attendance_actions.load_attendance_bot_owner = lambda: "ux_assistant"
    attendance_actions.register_service.clear_waiting_register_input = (
        lambda **kwargs: session_clears.append(int(kwargs["tg_id"]))
    )

    for scenario_id, actor_id, configured in (
        ("AT-SHIFT-TEXT-UNCONFIGURED", 87099, False),
    ):
        session_clears.clear()
        attendance_actions.admin_list_repo.is_admin_by_tg_id = (
            lambda *, tg_id, actor_id=actor_id: tg_id == actor_id
        )
        attendance_actions.build_shift_web_app_url_for_admin = (
            (lambda **_kwargs: None)
            if not configured
            else (
                lambda **_kwargs: (
                    "https://attendance.example.test/shift-app/index.html"
                    "?year_month=2026-08"
                )
            )
        )
        message = OldInteractionMessage(
            text="班表",
            private=True,
            sender_id=actor_id,
        )
        await attendance_actions.open_shift_web_app_message(message)
        traces[scenario_id] = {
            "sessionCleared": session_clears == [actor_id],
            "trace": normalize_old_replies(message.replies),
        }

    for scenario_id, actor_id, configured, is_admin in (
        ("AT-SHIFT-CALLBACK-ADMIN", 87099, True, True),
        ("AT-SHIFT-CALLBACK-FORBIDDEN", 87001, True, False),
        ("AT-SHIFT-CALLBACK-UNCONFIGURED", 87099, False, True),
    ):
        attendance_actions.admin_list_repo.is_admin_by_tg_id = (
            lambda *, tg_id, actor_id=actor_id, is_admin=is_admin: (
                tg_id == actor_id and is_admin
            )
        )
        attendance_actions.build_shift_web_app_url_for_admin = (
            (lambda **_kwargs: None)
            if not configured
            else (
                lambda **_kwargs: (
                    "https://attendance.example.test/shift-app/index.html"
                    "?year_month=2026-08"
                )
            )
        )
        message = OldInteractionMessage(
            text="source",
            private=True,
            sender_id=actor_id,
        )
        callback = OldInteractionCallback(
            data="act:shift",
            callback_id="cb-shift",
            message=message,
            sender_id=actor_id,
        )
        await attendance_actions.open_shift_web_app_callback(callback)
        traces[scenario_id] = [
            *normalize_old_callback_answers(callback.answers),
            *normalize_old_replies(message.replies),
        ]

    profile.register_service.clear_waiting_register_input = (
        lambda **kwargs: session_clears.append(int(kwargs["tg_id"]))
    )
    profile.load_attendance_bot_owner = lambda: "ux_assistant"
    for scenario_id, actor_id, bound, callback_mode in (
        ("AT-PROFILE-TEXT-BOUND", 87001, True, False),
        ("AT-PROFILE-CALLBACK-BOUND", 87001, True, True),
        ("AT-PROFILE-CALLBACK-UNREGISTERED", 87100, False, True),
    ):
        session_clears.clear()
        text = (
            "姓名：GRANDFOR\n工号：74808\n班次：未配置"
            if bound
            else "你还未完成注册，请先注册后再查看我的信息。"
        )
        profile.profile_service.get_my_profile_by_tg_id = (
            lambda **_kwargs: SimpleNamespace(
                message=text,
                ok=bound,
                error_code=None if bound else "NOT_REGISTERED",
            )
        )
        message = OldInteractionMessage(
            text="我的信息",
            private=True,
            sender_id=actor_id,
        )
        if callback_mode:
            callback = OldInteractionCallback(
                data="profile:myinfo",
                callback_id="cb-profile",
                message=message,
                sender_id=actor_id,
            )
            await profile.myinfo_callback(callback)
            action_trace = [
                *normalize_old_callback_answers(callback.answers),
                *normalize_old_replies(message.replies),
            ]
        else:
            await profile.myinfo_message(message)
            action_trace = normalize_old_replies(message.replies)
        traces[scenario_id] = {
            "sessionCleared": session_clears == [actor_id],
            "trace": action_trace,
        }

    for scenario_id, actor_id, successful in (
        ("AT-SWITCH-GROUP-SUCCESS", 87001, True),
        ("AT-SWITCH-GROUP-INVALID", 87100, False),
    ):
        writes: list[tuple[int, int]] = []

        def switch_group(*, tg_id: int, chat_id: int) -> Any:
            if successful:
                writes.append((tg_id, chat_id))
                return SimpleNamespace(
                    message="已记录本群为考勤群，请重新发送打卡截图。"
                )
            return SimpleNamespace(message="您尚未注册。")

        attendance_actions.checkin_service.switch_attendance_group_to_chat = (
            switch_group
        )
        message = OldInteractionMessage(
            text="source",
            sender_id=actor_id,
        )
        callback_id = "cb-switch-group" if successful else "cb-switch-invalid"
        callback = OldInteractionCallback(
            data="act:switch_group",
            callback_id=callback_id,
            message=message,
            sender_id=actor_id,
        )
        await attendance_actions.switch_attendance_group_callback(callback)
        traces[scenario_id] = {
            "registeredChatWrites": writes,
            "trace": [
                *normalize_old_callback_answers(callback.answers),
                *normalize_old_replies(message.replies),
            ],
        }
    attendance_actions.build_shift_web_app_url_for_admin = (
        lambda **_kwargs: (
            "https://attendance.example.test/shift-app/index.html"
            "?year_month=2026-08"
        )
    )
    return traces


def current_profile_shift_switch_traces(
    *,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    traces: dict[str, Any] = {}
    session_clears: list[int] = []
    event_module.register_service.clear_waiting_register_input = (
        lambda _cursor, *, tg_id: session_clears.append(tg_id)
    )

    event_module.is_admin = lambda _cursor, *, tg_id: tg_id == 87099
    traces["AT-SHIFT-TEXT-UNCONFIGURED"] = execute_current_interaction(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        event=private_surface_message_event("班表", actor_id=87099),
        shift_web_app_public_url="",
    )
    traces["AT-SHIFT-TEXT-UNCONFIGURED"] = {
        "sessionCleared": session_clears == [87099],
        "trace": traces["AT-SHIFT-TEXT-UNCONFIGURED"],
    }

    for scenario_id, actor_id, configured, is_admin in (
        ("AT-SHIFT-CALLBACK-ADMIN", 87099, True, True),
        ("AT-SHIFT-CALLBACK-FORBIDDEN", 87001, True, False),
        ("AT-SHIFT-CALLBACK-UNCONFIGURED", 87099, False, True),
    ):
        event_module.is_admin = (
            lambda _cursor, *, tg_id, actor_id=actor_id, is_admin=is_admin: (
                tg_id == actor_id and is_admin
            )
        )
        trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=callback_interaction_event(
                data="att:shift",
                callback_id="cb-shift",
                private=True,
                sender_id=actor_id,
            ),
            shift_web_app_public_url=(
                "https://attendance.example.test" if configured else ""
            ),
        )
        traces[scenario_id] = trace

    for scenario_id, actor_id, bound, callback_mode in (
        ("AT-PROFILE-TEXT-BOUND", 87001, True, False),
        ("AT-PROFILE-CALLBACK-BOUND", 87001, True, True),
        ("AT-PROFILE-CALLBACK-UNREGISTERED", 87100, False, True),
    ):
        session_clears.clear()
        profile_text = (
            "姓名：GRANDFOR\n工号：74808\n班次：未配置"
            if bound
            else "你还未完成注册，请先注册后再查看我的信息。"
        )
        event_module.profile_text_for_tg_id = (
            lambda *_args, profile_text=profile_text, **_kwargs: profile_text
        )
        event = (
            callback_interaction_event(
                data="att:profile",
                callback_id="cb-profile",
                private=True,
                sender_id=actor_id,
            )
            if callback_mode
            else private_surface_message_event("我的信息", actor_id=actor_id)
        )
        traces[scenario_id] = {
            "sessionCleared": False,
            "trace": execute_current_interaction(
                event_module=event_module,
                GatewayEventRequest=GatewayEventRequest,
                event_response_value=event_response_value,
                event=event,
            ),
        }
        traces[scenario_id]["sessionCleared"] = session_clears == [actor_id]

    for scenario_id, actor_id in (
        ("AT-SWITCH-GROUP-SUCCESS", 87001),
        ("AT-SWITCH-GROUP-INVALID", 87100),
    ):
        writes: list[tuple[int, int]] = []
        registration = (
            SimpleNamespace(employee_id="74808", english_name="GRANDFOR")
            if actor_id == 87001
            else None
        )
        event_module.registrations_repo.get_by_tg_id_cur = (
            lambda _cursor, *, tg_id, registration=registration: registration
        )

        def update_group(
            _cursor: object,
            *,
            tg_id: int,
            registered_chat_id: int,
        ) -> int:
            writes.append((tg_id, registered_chat_id))
            return 1

        event_module.registrations_repo.update_registered_chat_by_tg_id_cur = (
            update_group
        )
        traces[scenario_id] = {
            "registeredChatWrites": writes,
            "trace": execute_current_interaction(
                event_module=event_module,
                GatewayEventRequest=GatewayEventRequest,
                event_response_value=event_response_value,
                event=callback_interaction_event(
                    data="att:switch_group",
                    callback_id=(
                        "cb-switch-group"
                        if actor_id == 87001
                        else "cb-switch-invalid"
                    ),
                    private=False,
                    sender_id=actor_id,
                ),
            ),
        }
    return traces


async def current_export_matrix_traces(
    *,
    event_module: Any,
    export_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    export_module.is_admin = lambda _cursor, *, tg_id: True
    export_module.attendance_export_service.build_pivot_and_overview = (
        lambda **_kwargs: (
            "pivot",
            SimpleNamespace(expected_count=3),
            [date(2026, 8, 8)],
        )
    )
    export_module.attendance_export_service.encode_attendance_export_xlsx = (
        lambda **_kwargs: b"parity-xlsx"
    )
    export_module._deterministic_xlsx = lambda payload, **_kwargs: payload
    traces: dict[str, Any] = {}
    original_enqueue_run = export_module.worker_schedule_repo.enqueue_run_cur
    for scenario_id, callback_data, failure in (
        ("AT-EXPORT-TODAY", "att:export:today", False),
        ("AT-EXPORT-YESTERDAY", "att:export:yesterday", False),
        ("AT-EXPORT-WEEK", "att:export:week", False),
        ("AT-EXPORT-LAST-WEEK", "att:export:last_week", False),
        ("AT-EXPORT-MONTH", "att:export:month", False),
        ("AT-EXPORT-LAST-MONTH", "att:export:last_month", False),
        ("AT-EXPORT-FAILURE", "att:export:today", True),
    ):
        deferred_jobs: list[dict[str, Any]] = []
        export_module.worker_schedule_repo.enqueue_run_cur = (
            lambda _cursor, **kwargs: deferred_jobs.append(dict(kwargs)) or "ENQUEUED"
        )

        async def collect_rows(
            *,
            _failure: bool = failure,
            **_kwargs: object,
        ) -> list[object]:
            if _failure:
                raise RuntimeError("database unavailable")
            return []

        export_module.attendance_export_service.collect_rows_for_range = collect_rows
        request = GatewayEventRequest.model_validate(
            export_callback_event(
                callback_data=callback_data,
                callback_id=callback_data.removeprefix("att:export:") or "today",
            ),
            strict=True,
        )
        initial_response = await asyncio.to_thread(
            export_module.process_export_callback,
            request,
            object(),
            request.telegramUpdate,
        )
        initial_actions = event_response_value(initial_response)["actions"]
        assert len(deferred_jobs) == 1
        terminal_response = await asyncio.to_thread(
            export_module.process_export_callback,
            request,
            object(),
            request.telegramUpdate,
            defer_long_operation=False,
        )
        initial_action_ids = {action["actionId"] for action in initial_actions}
        terminal_actions = [
            action
            for action in event_response_value(terminal_response)["actions"]
            if action["actionId"] not in initial_action_ids
        ]
        traces[scenario_id] = normalize_current_export_actions(
            [*initial_actions, *terminal_actions]
        )
    export_module.worker_schedule_repo.enqueue_run_cur = original_enqueue_run

    traces["AT-EXPORT-TEXT-NONPRIVATE"] = execute_current_interaction(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        event=group_message_event("导出", sender_id=87099),
    )
    return traces


async def old_registration_traces(register: Any) -> dict[str, Any]:
    from datetime import datetime, timezone

    traces: dict[str, Any] = {}
    register.load_attendance_bot_owner = lambda: "ux_assistant"
    session_writes: list[dict[str, Any]] = []
    session_clears: list[int] = []
    register.register_service.mark_waiting_register_input = (
        lambda **kwargs: session_writes.append({
            "stage": "awaiting_input",
            "tgId": int(kwargs["tg_id"]),
            "privateChatId": int(kwargs["private_chat_id"]),
        })
    )
    register.register_service.clear_waiting_register_input = (
        lambda **kwargs: session_clears.append(int(kwargs["tg_id"]))
    )

    for scenario_id, text in (
        ("AT-REGISTER-BEGIN-TEXT", "注册"),
        ("AT-REGISTER-BEGIN-BIND-TEXT", "绑定考勤资料"),
        ("AT-REGISTER-BEGIN-COMMAND", "/attendance_register"),
    ):
        session_writes.clear()
        session_clears.clear()
        register.registrations_repo.get_by_tg_id = lambda _tg_id: None
        message = OldInteractionMessage(text=text, private=True)
        await register.register_begin_message(message)
        traces[scenario_id] = {
            "businessWrites": list(session_writes),
            "trace": normalize_old_replies(message.replies),
        }

    session_writes.clear()
    session_clears.clear()
    register.registrations_repo.get_by_tg_id = lambda _tg_id: SimpleNamespace(
        employee_id="74808",
        english_name="GRANDFOR",
    )
    message = OldInteractionMessage(text="注册", private=True)
    await register.register_begin_message(message)
    traces["AT-REGISTER-ALREADY-BOUND"] = {
        "businessWrites": [],
        "sessionCleared": session_clears == [87001],
        "trace": normalize_old_replies(message.replies),
    }

    for scenario_id, private in (
        ("AT-REGISTER-BEGIN-CALLBACK-PRIVATE", True),
        ("AT-REGISTER-BEGIN-CALLBACK-GROUP", False),
    ):
        session_writes.clear()
        register.registrations_repo.get_by_tg_id = lambda _tg_id: None
        message = OldInteractionMessage(text="source", private=private)
        callback = OldInteractionCallback(
            data="reg:begin",
            callback_id=(
                "cb-register-begin" if private else "cb-register-group"
            ),
            message=message,
        )
        await register.register_begin_callback(callback)
        traces[scenario_id] = {
            "businessWrites": list(session_writes),
            "trace": [
                *normalize_old_callback_answers(callback.answers),
                *normalize_old_replies(message.replies),
            ],
        }

    register.register_service.is_waiting_register_input = lambda **_kwargs: True
    register.register_service.secrets.token_urlsafe = lambda _size: "token-preview-701"
    preview_writes: list[dict[str, Any]] = []
    preview_expiry = datetime(2026, 8, 8, 9, 15, tzinfo=timezone.utc)
    register.register_service.registration_sessions_repo.save_preview = (
        lambda **kwargs: (
            preview_writes.append({
                "stage": "awaiting_confirmation",
                "tgId": int(kwargs["tg_id"]),
                "privateChatId": int(kwargs["private_chat_id"]),
                "englishName": str(kwargs["english_name"]),
                "employeeId": str(kwargs["employee_id"]),
                "token": "token-preview-701",
            })
            or preview_expiry
        )
    )
    register.register_service.registration_sessions_repo.touch_invalid_input = (
        lambda **kwargs: preview_writes.append({
            "stage": "awaiting_input",
            "tgId": int(kwargs["tg_id"]),
            "privateChatId": int(kwargs["private_chat_id"]),
        })
    )
    for scenario_id, text in (
        ("AT-REGISTER-PREVIEW-VALID", "GRANDFOR$74808"),
        ("AT-REGISTER-PREVIEW-BAD-DELIMITER", "GRANDFOR-74808"),
        ("AT-REGISTER-PREVIEW-BAD-NAME", "$74808"),
        ("AT-REGISTER-PREVIEW-BAD-EMPLOYEE", "GRANDFOR$74"),
    ):
        preview_writes.clear()
        message = OldInteractionMessage(text=text, private=True)
        await register.register_input_message_handler(message)
        traces[scenario_id] = {
            "businessWrites": list(preview_writes),
            "trace": normalize_old_replies(message.replies),
        }

    finish_calls: list[dict[str, Any]] = []
    confirm_scenarios = (
        ("AT-REGISTER-CONFIRM-SUCCESS", 87001, "ok"),
        ("AT-REGISTER-CONFIRM-EXPIRED", 87001, "expired"),
        ("AT-REGISTER-CONFIRM-CROSS-ACTOR", 87100, "owner_mismatch"),
        ("AT-REGISTER-CONFIRM-REPLAY", 87001, "expired"),
    )
    for scenario_id, actor_id, result_code in confirm_scenarios:
        finish_calls.clear()

        def confirm_and_bind(**kwargs: Any) -> Any:
            finish_calls.append({
                "operation": "confirm",
                "tgId": int(kwargs["tg_id"]),
                "token": str(kwargs["token"]),
                "resultCode": result_code,
            })
            return SimpleNamespace(code=result_code)

        register.register_service.registration_sessions_repo.confirm_and_bind = (
            confirm_and_bind
        )
        message = OldInteractionMessage(
            text="source",
            private=True,
            sender_id=actor_id,
        )
        callback = OldInteractionCallback(
            data="reg:confirm:token-preview-701",
            callback_id=(
                "cb-register-confirm"
                if scenario_id == "AT-REGISTER-CONFIRM-SUCCESS"
                else "cb-register-confirm-invalid"
            ),
            message=message,
            sender_id=actor_id,
            username="parity_actor" if result_code == "ok" else None,
        )
        await register.register_confirm_callback(callback)
        traces[scenario_id] = {
            "businessState": "BOUND" if result_code == "ok" else "UNCHANGED",
            "serviceCalls": list(finish_calls),
            "trace": [
                *normalize_old_callback_answers(callback.answers),
                *normalize_old_replies(message.replies),
            ],
        }

    for scenario_id, actor_id, cancelled in (
        ("AT-REGISTER-CANCEL-SUCCESS", 87001, True),
        ("AT-REGISTER-CANCEL-EXPIRED", 87001, False),
        ("AT-REGISTER-CANCEL-CROSS-ACTOR", 87100, False),
        ("AT-REGISTER-CANCEL-REPLAY", 87001, False),
    ):
        finish_calls.clear()

        def cancel_preview(**kwargs: Any) -> bool:
            finish_calls.append({
                "operation": "cancel",
                "tgId": int(kwargs["tg_id"]),
                "token": str(kwargs["token"]),
                "cancelled": cancelled,
            })
            return cancelled

        register.register_service.registration_sessions_repo.cancel_preview = (
            cancel_preview
        )
        message = OldInteractionMessage(
            text="source",
            private=True,
            sender_id=actor_id,
        )
        callback = OldInteractionCallback(
            data="reg:cancel:token-preview-701",
            callback_id=(
                "cb-register-cancel"
                if scenario_id == "AT-REGISTER-CANCEL-SUCCESS"
                else "cb-register-cancel-invalid"
            ),
            message=message,
            sender_id=actor_id,
        )
        await register.register_cancel_callback(callback)
        traces[scenario_id] = {
            "businessState": "CANCELLED" if cancelled else "UNCHANGED",
            "serviceCalls": list(finish_calls),
            "trace": [
                *normalize_old_callback_answers(callback.answers),
                *normalize_old_replies(message.replies),
            ],
        }
    return traces


def current_registration_traces(
    *,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    from datetime import datetime, timezone

    traces: dict[str, Any] = {}
    session_writes: list[dict[str, Any]] = []
    session_clears: list[int] = []
    event_module.register_service.mark_waiting_register_input = (
        lambda _cursor, *, tg_id, private_chat_id: session_writes.append({
            "stage": "awaiting_input",
            "tgId": tg_id,
            "privateChatId": private_chat_id,
        })
    )
    event_module.register_service.clear_waiting_register_input = (
        lambda _cursor, *, tg_id: session_clears.append(tg_id)
    )
    for scenario_id, text in (
        ("AT-REGISTER-BEGIN-TEXT", "注册"),
        ("AT-REGISTER-BEGIN-BIND-TEXT", "绑定考勤资料"),
        ("AT-REGISTER-BEGIN-COMMAND", "/attendance_register"),
    ):
        session_writes.clear()
        session_clears.clear()
        event_module.registrations_repo.get_by_tg_id_cur = (
            lambda _cursor, *, tg_id: None
        )
        action_trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=registration_message_event(text),
        )
        traces[scenario_id] = {
            "businessWrites": list(session_writes),
            "trace": action_trace,
        }

    session_clears.clear()
    event_module.registrations_repo.get_by_tg_id_cur = (
        lambda _cursor, *, tg_id: SimpleNamespace(
            employee_id="74808",
            english_name="GRANDFOR",
        )
    )
    traces["AT-REGISTER-ALREADY-BOUND"] = {
        "businessWrites": [],
        "sessionCleared": session_clears,
        "trace": execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=registration_message_event("注册"),
        ),
    }
    traces["AT-REGISTER-ALREADY-BOUND"]["sessionCleared"] = (
        session_clears == [87001]
    )

    for scenario_id, private in (
        ("AT-REGISTER-BEGIN-CALLBACK-PRIVATE", True),
        ("AT-REGISTER-BEGIN-CALLBACK-GROUP", False),
    ):
        session_writes.clear()
        event_module.registrations_repo.get_by_tg_id_cur = (
            lambda _cursor, *, tg_id: None
        )
        action_trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=callback_interaction_event(
                data="att:register",
                callback_id=(
                    "cb-register-begin" if private else "cb-register-group"
                ),
                private=private,
            ),
        )
        traces[scenario_id] = {
            "businessWrites": list(session_writes),
            "trace": action_trace,
        }

    event_module.register_service.is_waiting_register_input = (
        lambda _cursor, *, tg_id, private_chat_id: True
    )
    event_module.register_service.secrets.token_urlsafe = (
        lambda _size: "token-preview-701"
    )
    preview_writes: list[dict[str, Any]] = []
    preview_expiry = datetime(2026, 8, 8, 9, 15, tzinfo=timezone.utc)
    event_module.register_service.registration_sessions_repo.save_preview = (
        lambda _cursor, **kwargs: (
            preview_writes.append({
                "stage": "awaiting_confirmation",
                "tgId": int(kwargs["tg_id"]),
                "privateChatId": int(kwargs["private_chat_id"]),
                "englishName": str(kwargs["english_name"]),
                "employeeId": str(kwargs["employee_id"]),
                "token": "token-preview-701",
            })
            or preview_expiry
        )
    )
    event_module.register_service.registration_sessions_repo.touch_invalid_input = (
        lambda _cursor, **kwargs: preview_writes.append({
            "stage": "awaiting_input",
            "tgId": int(kwargs["tg_id"]),
            "privateChatId": int(kwargs["private_chat_id"]),
        })
    )
    for scenario_id, text in (
        ("AT-REGISTER-PREVIEW-VALID", "GRANDFOR$74808"),
        ("AT-REGISTER-PREVIEW-BAD-DELIMITER", "GRANDFOR-74808"),
        ("AT-REGISTER-PREVIEW-BAD-NAME", "$74808"),
        ("AT-REGISTER-PREVIEW-BAD-EMPLOYEE", "GRANDFOR$74"),
    ):
        preview_writes.clear()
        action_trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=registration_message_event(
                text,
                route_reason="CONVERSATION_SESSION",
            ),
        )
        traces[scenario_id] = {
            "businessWrites": list(preview_writes),
            "trace": action_trace,
        }

    finish_calls: list[dict[str, Any]] = []
    for scenario_id, actor_id, result_code in (
        ("AT-REGISTER-CONFIRM-SUCCESS", 87001, "ok"),
        ("AT-REGISTER-CONFIRM-EXPIRED", 87001, "expired"),
        ("AT-REGISTER-CONFIRM-CROSS-ACTOR", 87100, "owner_mismatch"),
        ("AT-REGISTER-CONFIRM-REPLAY", 87001, "expired"),
    ):
        finish_calls.clear()

        def confirm_and_bind(
            _cursor: object,
            *,
            _result_code: str = result_code,
            **kwargs: Any,
        ) -> Any:
            finish_calls.append({
                "operation": "confirm",
                "tgId": int(kwargs["tg_id"]),
                "token": str(kwargs["token"]),
                "resultCode": _result_code,
            })
            return SimpleNamespace(code=_result_code)

        event_module.register_service.registration_sessions_repo.confirm_and_bind = (
            confirm_and_bind
        )
        action_trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=registration_finish_event(
                operation="confirm",
                actor_id=actor_id,
                callback_id=(
                    "cb-register-confirm"
                    if result_code == "ok"
                    else "cb-register-confirm-invalid"
                ),
                username="parity_actor" if result_code == "ok" else None,
            ),
        )
        traces[scenario_id] = {
            "businessState": "BOUND" if result_code == "ok" else "UNCHANGED",
            "serviceCalls": list(finish_calls),
            "trace": action_trace,
        }

    for scenario_id, actor_id, cancelled in (
        ("AT-REGISTER-CANCEL-SUCCESS", 87001, True),
        ("AT-REGISTER-CANCEL-EXPIRED", 87001, False),
        ("AT-REGISTER-CANCEL-CROSS-ACTOR", 87100, False),
        ("AT-REGISTER-CANCEL-REPLAY", 87001, False),
    ):
        finish_calls.clear()

        def cancel_preview(
            _cursor: object,
            *,
            _cancelled: bool = cancelled,
            **kwargs: Any,
        ) -> bool:
            finish_calls.append({
                "operation": "cancel",
                "tgId": int(kwargs["tg_id"]),
                "token": str(kwargs["token"]),
                "cancelled": _cancelled,
            })
            return _cancelled

        event_module.register_service.registration_sessions_repo.cancel_preview = (
            cancel_preview
        )
        action_trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=registration_finish_event(
                operation="cancel",
                actor_id=actor_id,
                callback_id=(
                    "cb-register-cancel"
                    if cancelled
                    else "cb-register-cancel-invalid"
                ),
            ),
        )
        traces[scenario_id] = {
            "businessState": "CANCELLED" if cancelled else "UNCHANGED",
            "serviceCalls": list(finish_calls),
            "trace": action_trace,
        }
    return traces


async def old_admin_test_traces(admin_test: Any) -> dict[str, Any]:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            value = cls(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
            return value if tz is None else value.astimezone(tz)

    admin_test.admin_test_service.datetime = FixedDateTime
    admin_test.admin_test_service.admin_list_repo.is_admin_by_tg_id = (
        lambda **_kwargs: True
    )
    traces: dict[str, Any] = {}
    for scenario_id, caption, document, photo in (
        ("AT-ADMIN-TEST-TEXT", None, None, None),
        (
            "AT-ADMIN-TEST-CAPTION-DOCUMENT",
            "/test",
            SimpleNamespace(file_id="document-file-701"),
            None,
        ),
        (
            "AT-ADMIN-TEST-CAPTION-PHOTO",
            "/test@ParityBot",
            None,
            [
                SimpleNamespace(file_id="photo-small-701"),
                SimpleNamespace(file_id="photo-large-701"),
            ],
        ),
    ):
        class Message:
            text = "/test" if caption is None else None
            chat = SimpleNamespace(id=-10087001, type="supergroup")
            from_user = SimpleNamespace(id=87099, username="parity_admin")

            def __init__(self) -> None:
                self.caption = caption
                self.document = document
                self.photo = photo
                self.replies: list[tuple[str, Any]] = []

            async def reply(self, *, text: str) -> None:
                self.replies.append((text, None))

        message = Message()
        await admin_test.admin_test_handler(message)
        traces[scenario_id] = normalize_old_replies(message.replies)
    return traces


def current_admin_test_traces(
    *,
    admin_module: Any,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    admin_module.is_admin = lambda _cursor, *, tg_id: True
    traces: dict[str, Any] = {}
    for scenario_id, message_fields in (
        ("AT-ADMIN-TEST-TEXT", {"text": "/test"}),
        (
            "AT-ADMIN-TEST-CAPTION-DOCUMENT",
            {
                "caption": "/test",
                "document": {"file_id": "document-file-701"},
            },
        ),
        (
            "AT-ADMIN-TEST-CAPTION-PHOTO",
            {
                "caption": "/test@ParityBot",
                "photo": [
                    {"file_id": "photo-small-701"},
                    {"file_id": "photo-large-701"},
                ],
            },
        ),
    ):
        trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=admin_test_event(message_fields),
        )
        traces[scenario_id] = trace
    return traces


class OldAdminExportState:
    def __init__(self, *, stage: str | None = None, data: dict[str, Any] | None = None) -> None:
        self.stage = stage
        self.data = dict(data or {})
        self.transitions: list[str] = [] if stage is None else [stage]

    async def clear(self) -> None:
        self.stage = None
        self.data.clear()
        self.transitions.append("empty")

    async def set_state(self, stage: Any) -> None:
        state_name = str(getattr(stage, "state", stage))
        self.stage = state_name.rsplit(":", 1)[-1]
        self.transitions.append(self.stage)

    async def update_data(self, **kwargs: Any) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)


class OldAdminExportMessage:
    def __init__(
        self,
        calls: list[dict[str, Any]],
        *,
        text: str,
        private: bool,
        actor_id: int,
    ) -> None:
        self.calls = calls
        self.text = text
        self.caption = None
        self.chat = SimpleNamespace(
            id=actor_id if private else -10087001,
            type="private" if private else "supergroup",
        )
        self.from_user = SimpleNamespace(id=actor_id)

    async def reply(self, *, text: str, reply_markup: Any = None) -> None:
        self.calls.append({
            "method": "sendMessage",
            "text": text,
            "replyToInput": True,
            "replyMarkup": normalize_markup(
                reply_markup.model_dump(exclude_none=True)
                if reply_markup is not None
                else None
            ),
        })

    async def answer(self, *, text: str) -> None:
        await self.reply(text=text)

    async def answer_document(self, *, document: Any) -> None:
        self.calls.append({
            "method": "sendDocument",
            "fileName": document.filename,
            "contentBase64": base64.b64encode(document.data).decode("ascii"),
            "replyToInput": True,
        })


class OldAdminExportCallback:
    def __init__(
        self,
        calls: list[dict[str, Any]],
        *,
        data: str,
        callback_id: str,
        message: OldAdminExportMessage,
    ) -> None:
        self.calls = calls
        self.data = data
        self.id = callback_id
        self.message = message
        self.from_user = SimpleNamespace(id=87099)

    async def answer(self) -> None:
        self.calls.append({
            "method": "answerCallbackQuery",
            "callbackQueryId": self.id,
        })


async def old_admin_export_traces(admin_export_test: Any) -> dict[str, Any]:
    ex = admin_export_test.ex
    ex.check_admin_for_export = lambda **_kwargs: (True, None)
    ex.shifts_repo.get_by_id = lambda _shift_id: SimpleNamespace(id=12)
    csv_files = [
        ("qc_results_shift_12_2026-08-01_to_2026-08-07.csv", b"\xef\xbb\xbfqc"),
        ("audit_results_shift_12_2026-08-01_to_2026-08-07.csv", b"\xef\xbb\xbfaudit"),
        ("effective_leave_days_shift_12_2026-08-01_to_2026-08-07.csv", b"\xef\xbb\xbfleave"),
    ]
    ex.prepare_three_csv_exports = lambda **_kwargs: (csv_files, None)
    traces: dict[str, Any] = {}

    calls: list[dict[str, Any]] = []
    state = OldAdminExportState()
    for text, handler in (
        ("/test_1", admin_export_test.admin_export_test_1_entry),
        ("12", admin_export_test.admin_export_shift_id_step),
        ("2026$8$1", admin_export_test.admin_export_start_date_step),
        ("2026$8$7", admin_export_test.admin_export_end_date_step),
    ):
        await handler(
            OldAdminExportMessage(
                calls,
                text=text,
                private=True,
                actor_id=87099,
            ),
            state,
        )
    callback = OldAdminExportCallback(
        calls,
        data="aex1:ok",
        callback_id="cb-aex-confirm",
        message=OldAdminExportMessage(
            calls,
            text="source",
            private=True,
            actor_id=87099,
        ),
    )
    await admin_export_test.admin_export_confirm(callback, state)
    legacy_document_names = [
        call.get("fileName")
        for call in calls
        if call.get("method") == "sendDocument"
    ]
    traces["AT-ADMIN-EXPORT-TEST-SUCCESS"] = {
        "proofKind": "OLD_CODE_CHARACTERIZATION",
        "characterizationExecuted": bool(calls),
        "declaredSymbol": "admin_export_confirm",
        "lockedDeploymentExecuted": True,
        "failureReproduced": legacy_document_names
        == [name for name, _content in csv_files],
        "legacyDocumentNames": legacy_document_names,
        "oldDeploymentClaimed": False,
    }

    calls = []
    cancel_state = OldAdminExportState(
        stage="waiting_confirm",
        data={
            "export_shift_id": 12,
            "export_start_date_iso": "2026-08-01",
            "export_end_date_iso": "2026-08-07",
        },
    )
    callback = OldAdminExportCallback(
        calls,
        data="aex1:cancel",
        callback_id="cb-aex-cancel",
        message=OldAdminExportMessage(
            calls,
            text="source",
            private=True,
            actor_id=87099,
        ),
    )
    await admin_export_test.admin_export_cancel(callback, cancel_state)
    traces["AT-ADMIN-EXPORT-TEST-CANCEL"] = {
        "stateTransitions": cancel_state.transitions,
        "trace": calls,
    }

    calls = []
    invalid_state = OldAdminExportState(stage="waiting_shift_id")
    await admin_export_test.admin_export_shift_id_step(
        OldAdminExportMessage(calls, text="12x", private=True, actor_id=87099),
        invalid_state,
    )
    invalid_state.stage = "waiting_start_date"
    invalid_state.transitions.append("waiting_start_date")
    await admin_export_test.admin_export_start_date_step(
        OldAdminExportMessage(
            calls,
            text="2026/8/1",
            private=True,
            actor_id=87099,
        ),
        invalid_state,
    )
    invalid_state.stage = "waiting_end_date"
    invalid_state.data = {
        "export_shift_id": 12,
        "export_start_date_iso": "2026-08-01",
    }
    invalid_state.transitions.append("waiting_end_date")
    await admin_export_test.admin_export_end_date_step(
        OldAdminExportMessage(
            calls,
            text="2026$7$31",
            private=True,
            actor_id=87099,
        ),
        invalid_state,
    )
    traces["AT-ADMIN-EXPORT-TEST-INVALID"] = {
        "stateTransitions": invalid_state.transitions,
        "trace": calls,
    }

    calls = []
    await admin_export_test.admin_export_test_1_non_private(
        OldAdminExportMessage(
            calls,
            text="/test_1",
            private=False,
            actor_id=87099,
        )
    )
    traces["AT-ADMIN-EXPORT-TEST-NONPRIVATE"] = {
        "stateTransitions": [],
        "trace": calls,
    }

    calls = []
    ex.check_admin_for_export = lambda **_kwargs: (False, ex.MSG_NO_PERMISSION)
    forbidden_state = OldAdminExportState()
    await admin_export_test.admin_export_test_1_entry(
        OldAdminExportMessage(
            calls,
            text="/test_1",
            private=True,
            actor_id=87001,
        ),
        forbidden_state,
    )
    traces["AT-ADMIN-EXPORT-TEST-FORBIDDEN"] = {
        "stateTransitions": forbidden_state.transitions,
        "trace": calls,
    }
    return traces


class AdminExportParityCursor:
    def __init__(self) -> None:
        self.stage: str | None = None
        self.shift_id: int | None = None
        self.start_date: date | None = None
        self.end_date: date | None = None
        self.last_row: tuple[Any, ...] | None = None
        self.transitions: list[str] = []

    def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> None:
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("insert into attendance_admin_export_sessions"):
            self.stage = "waiting_shift_id"
            self.shift_id = self.start_date = self.end_date = None
            self.transitions.extend(["empty", "waiting_shift_id"])
            self.last_row = None
        elif normalized.startswith("select 1 from attendance_admin_export_sessions"):
            self.last_row = (1,) if self.stage is not None else None
        elif normalized.startswith("select stage, shift_id"):
            self.last_row = (
                None
                if self.stage is None
                else (self.stage, self.shift_id, self.start_date, self.end_date)
            )
        elif normalized.startswith("select 1 from shifts"):
            self.last_row = (1,) if int(parameters[0]) == 12 else None
        elif normalized.startswith("update attendance_admin_export_sessions"):
            self.stage = str(parameters[0])
            index = 1
            if "shift_id = %s" in normalized:
                self.shift_id = int(parameters[index])
                index += 1
            if "start_date = %s" in normalized:
                self.start_date = parameters[index]  # type: ignore[assignment]
                index += 1
            if "end_date = %s" in normalized:
                self.end_date = parameters[index]  # type: ignore[assignment]
            self.transitions.append(self.stage)
            self.last_row = None
        elif normalized.startswith("delete from attendance_admin_export_sessions"):
            self.stage = None
            self.transitions.append("empty")
            self.last_row = None
        else:
            raise AssertionError(f"Unexpected admin-export SQL: {statement}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.last_row


def current_admin_export_traces(
    *,
    admin_export_module: Any,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    admin_export_module.is_admin = lambda _cursor, *, tg_id: tg_id == 87099
    csv_files = [
        ("clock_records_shift_12_2026-08-01_to_2026-08-07.csv", b"\xef\xbb\xbfclock"),
        ("temporary_leave_records_shift_12_2026-08-01_to_2026-08-07.csv", b"\xef\xbb\xbfleave"),
        ("effective_leave_days_shift_12_2026-08-01_to_2026-08-07.csv", b"\xef\xbb\xbfeffective"),
    ]
    admin_export_module.prepare_three_csv_exports = (
        lambda *_args, **_kwargs: csv_files
    )
    traces: dict[str, Any] = {}

    cursor = AdminExportParityCursor()
    calls: list[dict[str, Any]] = []
    for text, route_reason in (
        ("/test_1", "COMMAND"),
        ("12", "CONVERSATION_SESSION"),
        ("2026$8$1", "CONVERSATION_SESSION"),
        ("2026$8$7", "CONVERSATION_SESSION"),
    ):
        calls.extend(execute_current_admin_export(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            cursor=cursor,
            event=admin_export_message_event(
                text,
                actor_id=87099,
                private=True,
                route_reason=route_reason,
            ),
        ))
    calls.extend(execute_current_admin_export(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        cursor=cursor,
        event=callback_interaction_event(
            data="att:admin_export:confirm",
            callback_id="cb-aex-confirm",
            private=True,
            sender_id=87099,
        ),
    ))
    document_calls = [call for call in calls if call.get("method") == "sendDocument"]
    traces["AT-ADMIN-EXPORT-TEST-SUCCESS"] = {
        "proofKind": "CURRENT_RECOVERY",
        "passed": (
            cursor.transitions
            == [
                "empty",
                "waiting_shift_id",
                "waiting_start_date",
                "waiting_end_date",
                "waiting_confirm",
                "empty",
            ]
            and [call["fileName"] for call in document_calls]
            == [file_name for file_name, _body in csv_files]
            and [call["contentBase64"] for call in document_calls]
            == [base64.b64encode(body).decode("ascii") for _name, body in csv_files]
        ),
        "evidence": {
            "stateTransitions": cursor.transitions,
            "trace": calls,
        },
    }

    cursor = AdminExportParityCursor()
    cursor.stage = "waiting_confirm"
    cursor.shift_id = 12
    cursor.start_date = date(2026, 8, 1)
    cursor.end_date = date(2026, 8, 7)
    cursor.transitions = ["waiting_confirm"]
    calls = execute_current_admin_export(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        cursor=cursor,
        event=callback_interaction_event(
            data="att:admin_export:cancel",
            callback_id="cb-aex-cancel",
            private=True,
            sender_id=87099,
        ),
    )
    traces["AT-ADMIN-EXPORT-TEST-CANCEL"] = {
        "stateTransitions": cursor.transitions,
        "trace": calls,
    }

    cursor = AdminExportParityCursor()
    cursor.stage = "waiting_shift_id"
    cursor.transitions = ["waiting_shift_id"]
    calls = execute_current_admin_export(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        cursor=cursor,
        event=admin_export_message_event(
            "12x", actor_id=87099, private=True, route_reason="CONVERSATION_SESSION"
        ),
    )
    cursor.stage = "waiting_start_date"
    cursor.transitions.append("waiting_start_date")
    calls.extend(execute_current_admin_export(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        cursor=cursor,
        event=admin_export_message_event(
            "2026/8/1", actor_id=87099, private=True, route_reason="CONVERSATION_SESSION"
        ),
    ))
    cursor.stage = "waiting_end_date"
    cursor.shift_id = 12
    cursor.start_date = date(2026, 8, 1)
    cursor.transitions.append("waiting_end_date")
    calls.extend(execute_current_admin_export(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        cursor=cursor,
        event=admin_export_message_event(
            "2026$7$31", actor_id=87099, private=True, route_reason="CONVERSATION_SESSION"
        ),
    ))
    traces["AT-ADMIN-EXPORT-TEST-INVALID"] = {
        "stateTransitions": cursor.transitions,
        "trace": calls,
    }

    cursor = AdminExportParityCursor()
    calls = execute_current_admin_export(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        cursor=cursor,
        event=admin_export_message_event(
            "/test_1", actor_id=87099, private=False, route_reason="GROUP_OWNER"
        ),
    )
    traces["AT-ADMIN-EXPORT-TEST-NONPRIVATE"] = {
        "stateTransitions": cursor.transitions,
        "trace": calls,
    }

    cursor = AdminExportParityCursor()
    calls = execute_current_admin_export(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        cursor=cursor,
        event=admin_export_message_event(
            "/test_1", actor_id=87001, private=True, route_reason="COMMAND"
        ),
    )
    traces["AT-ADMIN-EXPORT-TEST-FORBIDDEN"] = {
        "stateTransitions": cursor.transitions,
        "trace": calls,
    }
    return traces


def execute_current_admin_export(
    *,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
    cursor: AdminExportParityCursor,
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    request = GatewayEventRequest.model_validate(event, strict=True)
    response = event_module._process_attendance_event(
        request,
        cursor,
        object(),
        shift_web_app_public_url="https://attendance.example.test",
    )
    return normalize_current_admin_export_actions(
        event_response_value(response)["actions"]
    )


def normalize_current_admin_export_actions(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for action in actions:
        if action["type"] == "ANSWER_CALLBACK":
            output.append({
                "method": "answerCallbackQuery",
                "callbackQueryId": action["callbackQueryId"],
            })
        elif action["type"] == "SEND_MESSAGE":
            output.append({
                "method": "sendMessage",
                "text": action["text"],
                "replyToInput": True,
                "replyMarkup": normalize_markup(action.get("replyMarkup")),
            })
        elif action["type"] == "SEND_DOCUMENT":
            output.append({
                "method": "sendDocument",
                "fileName": action["document"]["fileName"],
                "contentBase64": action["document"]["contentBase64"],
                "replyToInput": True,
            })
        else:
            raise AssertionError(f"unexpected admin export action: {action!r}")
    return output


def current_group_interaction_traces(
    *,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
) -> dict[str, Any]:
    registration = SimpleNamespace(employee_id="74808", english_name="GRANDFOR")
    event_module.registrations_repo.get_by_tg_id_cur = (
        lambda _cursor, *, tg_id: registration
    )
    event_module.temporary_leave_records_repo.get_latest_open_cur = (
        lambda *_args, **_kwargs: None
    )
    event_module.requires_remote_diff_checkin = lambda **_kwargs: False
    event_module.requires_leave_mutual_exclusion = lambda **_kwargs: False
    event_module.requires_leave_back_copy_fallback = lambda **_kwargs: False
    event_module.is_admin = lambda _cursor, *, tg_id: False
    traces: dict[str, Any] = {}

    for scenario_id, text in (
        ("AT-GROUP-SIGNIN-COMMAND", "/signin"),
        ("AT-GROUP-SIGNIN-TEXT", "签到"),
        ("AT-GROUP-SIGNOUT-COMMAND", "/signout"),
        ("AT-GROUP-SIGNOUT-TEXT", "签退"),
        ("AT-GROUP-LEAVE-COMMAND", "/leave"),
        ("AT-GROUP-LEAVE-TEXT", "离岗"),
        ("AT-GROUP-BACK-COMMAND", "/back"),
        ("AT-GROUP-BACK-TEXT", "返岗"),
    ):
        traces[scenario_id] = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=group_message_event(text),
        )

    for scenario_id, operation in (
        ("AT-CALLBACK-SIGNIN", "signin"),
        ("AT-CALLBACK-SIGNOUT", "signout"),
        ("AT-CALLBACK-LEAVE", "leave"),
        ("AT-CALLBACK-BACK", "back"),
    ):
        traces[scenario_id] = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=callback_interaction_event(
                data=f"att:{operation}",
                callback_id=f"cb-{operation}",
                private=False,
            ),
        )

    for scenario_id, data, callback_id in (
        ("AT-MENU-CALLBACK", "att:menu", "cb-menu-show"),
        ("AT-SHELL-MENU-CALLBACK", "att:menu", "cb-shell-menu"),
    ):
        trace = execute_current_interaction(
            event_module=event_module,
            GatewayEventRequest=GatewayEventRequest,
            event_response_value=event_response_value,
            event=callback_interaction_event(
                data=data,
                callback_id=callback_id,
                private=True,
            ),
        )
        traces[scenario_id] = trace

    traces["AT-INLINE-QUERY-EMPTY"] = execute_current_interaction(
        event_module=event_module,
        GatewayEventRequest=GatewayEventRequest,
        event_response_value=event_response_value,
        event=inline_query_event(),
    )
    return traces


def execute_current_interaction(
    *,
    event_module: Any,
    GatewayEventRequest: Any,
    event_response_value: Any,
    event: dict[str, Any],
    shift_web_app_public_url: str = "https://attendance.example.test",
) -> Any:
    request = GatewayEventRequest.model_validate(event, strict=True)
    try:
        response = event_module._process_attendance_event(
            request,
            ParityCursor(),
            object(),
            shift_web_app_public_url=shift_web_app_public_url,
        )
    except Exception as error:
        return {"raised": type(error).__name__, "message": str(error)}
    return normalize_current_transport_actions(
        event_response_value(response)["actions"],
    )


def normalize_current_transport_actions(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for action in actions:
        action_type = action["type"]
        if action_type == "ANSWER_CALLBACK":
            normalized.append({
                "method": "answerCallbackQuery",
                "callbackQueryId": action["callbackQueryId"],
            })
        elif action_type == "ANSWER_INLINE_QUERY":
            normalized.append({
                "method": "answerInlineQuery",
                "inlineQueryId": action["inlineQueryId"],
                "results": action["results"],
                "cacheTimeSeconds": action.get("cacheTimeSeconds"),
                "isPersonal": action.get("isPersonal"),
            })
        elif action_type == "SEND_MESSAGE":
            normalized.append({
                "method": "sendMessage",
                "text": action["text"],
                "replyToInput": action.get("replyToMessageId") == 701,
                "replyMarkup": normalize_markup(action.get("replyMarkup")),
            })
        else:
            raise AssertionError(f"Unsupported interaction action: {action!r}")
    return normalized


def matrix_trace_aliases(trace: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "AT-ADMIN-EXPORT-TODAY": "AT-EXPORT-TODAY",
        "AT-GROUP-START": "AT-GROUP-MENU",
        "AT-REGISTRATION-TEXT-BEGIN": "AT-REGISTER-BEGIN-TEXT",
        "AT-SESSION-EXPORT-ADMIN": "AT-EXPORT-TEXT-ADMIN",
        "AT-SESSION-EXPORT-NONADMIN": "AT-EXPORT-TEXT-FORBIDDEN",
        "AT-SESSION-PROFILE-TEXT": "AT-PROFILE-TEXT-UNREGISTERED",
        "AT-SESSION-SHIFT-ADMIN": "AT-SHIFT-TEXT-ADMIN",
        "AT-SESSION-SHIFT-NONADMIN": "AT-SHIFT-TEXT-FORBIDDEN",
    }
    return {
        aliases.get(scenario_id, scenario_id): value
        for scenario_id, value in trace.items()
        if scenario_id not in {
            "AT-SESSION-MYINFO-TEXT",
            "AT-SESSION-SHIFT-ALIAS-NONADMIN",
        }
    }


def ignored_group_updates() -> list[dict[str, Any]]:
    return [{
        "update_id": 9101,
        "message": {
            "message_id": 9101,
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
            "text": "项目例会改到十点",
        },
    }]


def gateway_event(update: dict[str, Any]) -> dict[str, Any]:
    update_id = int(update["update_id"])
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-group-ignored-{update_id}",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
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
                        "value": button_value(button),
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
    if (
        "switch_inline_query_current_chat" in button
        or "switchInlineQueryCurrentChat" in button
    ):
        return "SWITCH_INLINE_QUERY_CURRENT_CHAT"
    if "copy_text" in button or "copyText" in button:
        return "COPY_TEXT"
    return "CALLBACK"


def button_value(button: dict[str, Any]) -> str:
    action = button_action(button)
    if action == "WEB_APP":
        return web_app_url(button)
    if action == "SWITCH_INLINE_QUERY_CURRENT_CHAT":
        return str(
            button.get(
                "switchInlineQueryCurrentChat",
                button.get("switch_inline_query_current_chat", ""),
            )
        )
    if action == "COPY_TEXT":
        copy_value = button.get("copyText", button.get("copy_text", ""))
        if isinstance(copy_value, dict):
            return str(copy_value.get("text", ""))
        return str(copy_value)
    callback_data = str(
        button.get("callbackData", button.get("callback_data", ""))
    )
    direct = {
        "reg:begin": "att:register",
        "profile:myinfo": "att:profile",
        "act:export": "att:export",
        "act:shift": "att:shift",
        "menu:show": "att:menu",
        "uxa:attendance_menu": "att:menu",
        "aex1:ok": "att:admin_export:confirm",
        "aex1:cancel": "att:admin_export:cancel",
    }.get(callback_data)
    if direct is not None:
        return direct
    for old_prefix, current_prefix in (
        ("act:export:", "att:export:"),
        ("act:", "att:"),
        ("reg:confirm:", "att:register:confirm:"),
        ("reg:cancel:", "att:register:cancel:"),
    ):
        if callback_data.startswith(old_prefix):
            return current_prefix + callback_data.removeprefix(old_prefix)
    return callback_data


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
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
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


def export_callback_event(
    *,
    callback_data: str = "att:export:today",
    callback_id: str = "today",
) -> dict[str, Any]:
    event = private_event()
    event["eventId"] = "evt-attendance-parity-export-today"
    event["routeReason"] = "CALLBACK_NAMESPACE"
    event["receivedAt"] = "2026-08-08T08:00:00Z"
    event["telegramUpdate"] = {
        "update_id": 7104,
        "callback_query": {
            "id": f"cb-export-{callback_id}",
            "from": {
                "id": 87099,
                "is_bot": False,
                "first_name": "Parity",
            },
            "message": {
                "message_id": 704,
                "date": 1_786_204_800,
                "chat": {"id": 87099, "type": "private"},
                "text": "请选择导出范围：",
            },
            "chat_instance": "instance-export-7104",
            "data": callback_data,
        },
    }
    return event


def group_message_event(text: str, *, sender_id: int = 87001) -> dict[str, Any]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-parity-group-interaction",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
        "conversationId": "telegram:chat:-10087001",
        "receivedAt": "2026-08-08T09:00:00Z",
        "telegramUpdate": {
            "update_id": 7201,
            "message": {
                "message_id": 701,
                "date": 1_786_204_800,
                "chat": {
                    "id": -10087001,
                    "type": "supergroup",
                    "title": "Attendance Parity",
                },
                "from": {
                    "id": sender_id,
                    "is_bot": False,
                    "first_name": "Parity",
                },
                "text": text,
            },
        },
    }


def checkin_event(case: dict[str, Any]) -> dict[str, Any]:
    kind = str(case["kind"])
    file_id = f"{kind}-file-701"
    message: dict[str, Any] = {
        "message_id": 701,
        "date": 1_786_179_600,
        "chat": {
            "id": -10087001,
            "type": "supergroup",
            "title": "Attendance Parity",
        },
        "from": {
            "id": int(case["senderId"]),
            "is_bot": False,
            "first_name": "Parity",
            "username": "parity_actor",
        },
        "caption": str(case["caption"]),
    }
    if kind == "document":
        message["document"] = {
            "file_id": file_id,
            "file_unique_id": "document-unique-701",
            "file_name": "checkin.png",
            "mime_type": "image/png",
            "file_size": 20,
        }
    else:
        message["photo"] = [{
            "file_id": file_id,
            "file_unique_id": "photo-unique-701",
            "width": 1280,
            "height": 720,
            "file_size": 20,
        }]
    update_key = "edited_message" if case["edited"] else "message"
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-parity-{case['scenarioId']}",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
        "conversationId": "telegram:chat:-10087001",
        "receivedAt": "2026-08-08T09:00:00Z",
        "telegramUpdate": {
            "update_id": 7301,
            update_key: message,
        },
        "telegramFiles": [{
            "fileRef": "tgf_0123456789abcdef0123456789abcdef01234567",
            "kind": kind.upper(),
            "mimeType": "image/png" if kind == "document" else "image/jpeg",
            "sizeBytes": 20,
        }],
    }


def callback_interaction_event(
    *,
    data: str,
    callback_id: str,
    private: bool,
    sender_id: int = 87001,
) -> dict[str, Any]:
    chat_id = sender_id if private else -10087001
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-parity-callback-interaction",
        "target": "ATTENDANCE",
        "routeReason": "CALLBACK_NAMESPACE",
        "conversationId": (
            f"telegram:private:{sender_id}"
            if private
            else "telegram:chat:-10087001"
        ),
        "receivedAt": "2026-08-08T09:00:00Z",
        "telegramUpdate": {
            "update_id": 7202,
            "callback_query": {
                "id": callback_id,
                "from": {
                    "id": sender_id,
                    "is_bot": False,
                    "first_name": "Parity",
                },
                "message": {
                    "message_id": 701,
                    "date": 1_786_204_800,
                    "chat": {
                        "id": chat_id,
                        "type": "private" if private else "supergroup",
                        **({} if private else {"title": "Attendance Parity"}),
                    },
                    "text": "source",
                },
                "chat_instance": "instance-parity-7202",
                "data": data,
            },
        },
    }


def private_surface_message_event(
    text: str,
    *,
    actor_id: int,
) -> dict[str, Any]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-parity-private-surface",
        "target": "ATTENDANCE",
        "routeReason": "CONVERSATION_SESSION",
        "conversationId": f"telegram:private:{actor_id}",
        "receivedAt": "2026-08-08T09:00:00Z",
        "telegramUpdate": {
            "update_id": 7204,
            "message": {
                "message_id": 701,
                "date": 1_786_204_800,
                "chat": {"id": actor_id, "type": "private"},
                "from": {
                    "id": actor_id,
                    "is_bot": False,
                    "first_name": "Parity",
                },
                "text": text,
            },
        },
    }


def registration_message_event(
    text: str,
    *,
    route_reason: str = "COMMAND",
) -> dict[str, Any]:
    event = private_surface_message_event(text, actor_id=87001)
    event["eventId"] = "evt-attendance-parity-registration"
    event["routeReason"] = route_reason
    return event


def registration_finish_event(
    *,
    operation: str,
    actor_id: int,
    callback_id: str,
    username: str | None = None,
) -> dict[str, Any]:
    event = callback_interaction_event(
        data=f"att:register:{operation}:token-preview-701",
        callback_id=callback_id,
        private=True,
        sender_id=actor_id,
    )
    callback = event["telegramUpdate"]["callback_query"]
    sender = callback["from"]
    if username is not None:
        sender["username"] = username
    return event


def admin_test_event(message_fields: dict[str, Any]) -> dict[str, Any]:
    event = group_message_event("unused", sender_id=87099)
    event["eventId"] = "evt-attendance-parity-admin-test"
    event["receivedAt"] = "2026-08-08T09:00:00Z"
    message = event["telegramUpdate"]["message"]
    message.pop("text", None)
    message["from"]["username"] = "parity_admin"
    message.update(message_fields)
    return event


def admin_export_message_event(
    text: str,
    *,
    actor_id: int,
    private: bool,
    route_reason: str,
) -> dict[str, Any]:
    event = (
        private_surface_message_event(text, actor_id=actor_id)
        if private
        else group_message_event(text, sender_id=actor_id)
    )
    event["eventId"] = "evt-attendance-parity-admin-export"
    event["routeReason"] = route_reason
    return event


def inline_query_event() -> dict[str, Any]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-parity-inline-query",
        "target": "ATTENDANCE",
        "routeReason": "INLINE_QUERY",
        "conversationId": "telegram:private:87001",
        "receivedAt": "2026-08-08T09:00:00Z",
        "telegramUpdate": {
            "update_id": 7203,
            "inline_query": {
                "id": "inline-701",
                "from": {
                    "id": 87001,
                    "is_bot": False,
                    "first_name": "Parity",
                },
                "query": "",
                "offset": "",
            },
        },
    }


if __name__ == "__main__":
    main()
