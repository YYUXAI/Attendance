from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from gateway_provider.runtime_security import assert_no_telegram_owner_credentials


_ROOT = Path(__file__).resolve().parent
_REMOVED_TELEGRAM_OWNER_PATHS = (
    "main.py",
    "runtime.py",
    "webhook_app.py",
    "infra/bot.py",
    "infra/bot_commands.py",
    "infra/telegram_sender.py",
    "infra/telegram_webapp_auth.py",
    "infra/workspace_bot_env.py",
)
_RETIRED_PRODUCT_PATHS = (
    "domain/audit_notification_builder.py",
    "domain/temporary_leave_rules.py",
    "handlers/qc_callback.py",
    "handlers/qc_closeout_group_callback.py",
    "handlers/qc_message.py",
    "handlers/rest.py",
    "handlers/temporary_leave.py",
    "infra/qc_dm.py",
    "infra/qc_shift_summary_notice_key.py",
    "keyboards/leave_types.py",
    "keyboards/qc_closeout_inline.py",
    "keyboards/qc_inline.py",
    "repositories/effective_temporary_leaves_repo.py",
    "repositories/leave_applications_repo.py",
    "repositories/notification_queue_repo.py",
    "repositories/qc_exemption_fixed_list_repo.py",
    "repositories/qc_results_export_repo.py",
    "repositories/qc_results_repo.py",
    "repositories/qc_task_queue_repo.py",
    "repositories/temporary_leave_applications_repo.py",
    "repositories/temporary_qc_exemption_list_repo.py",
    "services/approval_service.py",
    "services/audit_service.py",
    "services/qc_draw_service.py",
    "services/qc_notice_display.py",
    "services/qc_private_notify_service.py",
    "services/qc_round_closeout_service.py",
    "services/qc_round_open_service.py",
    "services/qc_schedule_service.py",
    "services/qc_shift_summary_service.py",
    "services/qc_task_lifecycle_service.py",
    "services/qc_timeout_service.py",
    "services/rest_service.py",
    "services/temporary_leave_effective_poll_service.py",
    "services/temporary_leave_service.py",
    "tasks/notification_worker.py",
    "tasks/qc_private_notify_poll.py",
    "tasks/qc_round_closeout_poll.py",
    "tasks/qc_round_scheduler_poll.py",
    "tasks/qc_shift_summary_poll.py",
    "tasks/qc_timeout_worker.py",
    "tasks/temporary_leave_effective_poll.py",
)
_NON_PRODUCTION_PARTS = frozenset({".git", ".gitnexus", ".venv", "__pycache__"})
_TELEGRAM_OWNER_IMPORT_ROOTS = frozenset(
    {"aiogram", "pyrogram", "telebot", "telegram"}
)
_TELEGRAM_OWNER_DISTRIBUTIONS = frozenset(
    {
        "aiogram",
        "node-telegram-bot-api",
        "pyrogram",
        "pytelegrambotapi",
        "python-telegram-bot",
        "telegraf",
        "telebot",
        "telegram",
    }
)


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        relative = path.relative_to(_ROOT)
        if any(part in _NON_PRODUCTION_PARTS for part in relative.parts):
            continue
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        files.append(path)
    return sorted(files)


def test_attendance_has_no_telegram_network_client_imports() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            if any(
                name.partition(".")[0].lower() in _TELEGRAM_OWNER_IMPORT_ROOTS
                for name in imported
            ):
                violations.append(str(path.relative_to(_ROOT)))
    assert violations == []


def test_attendance_has_no_telegram_owner_entrypoints_or_dependency() -> None:
    remaining = [
        relative
        for relative in _REMOVED_TELEGRAM_OWNER_PATHS
        if (_ROOT / relative).exists()
    ]
    assert remaining == []
    requirements = (_ROOT / "requirements.txt").read_text(encoding="utf-8")
    requirement_names = {
        match.group(1).lower().replace("_", "-")
        for line in requirements.splitlines()
        if (match := re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line.strip()))
    }
    assert requirement_names.isdisjoint(_TELEGRAM_OWNER_DISTRIBUTIONS)

    for package_path in _ROOT.glob("package*.json"):
        package = json.loads(package_path.read_text(encoding="utf-8"))
        dependency_names = {
            name.lower()
            for section in ("dependencies", "devDependencies", "optionalDependencies")
            for name in package.get(section, {})
        }
        assert dependency_names.isdisjoint(_TELEGRAM_OWNER_DISTRIBUTIONS)


def test_attendance_production_sources_have_no_direct_bot_api_calls() -> None:
    violations = [
        str(path.relative_to(_ROOT))
        for path in _production_python_files()
        if "scripts" not in path.relative_to(_ROOT).parts
        and "api.telegram.org" in path.read_text(encoding="utf-8", errors="strict")
    ]
    assert violations == []


def test_retired_attendance_products_have_no_executable_modules() -> None:
    remaining = [
        relative
        for relative in _RETIRED_PRODUCT_PATHS
        if (_ROOT / relative).exists()
    ]

    assert remaining == []
    # temporary_leave_records_repo is intentionally current truth: it owns the
    # lightweight group 离岗/返岗 record, not the retired leave-approval product.
    assert (_ROOT / "repositories/temporary_leave_records_repo.py").is_file()


def test_attendance_configuration_has_no_bot_token_or_transport_mode() -> None:
    checked = [
        _ROOT / ".env.example",
        _ROOT / "Dockerfile",
        _ROOT / "start_all.sh",
        _ROOT / "start_all.bat",
    ]
    forbidden = (
        "TELEGRAM_BOT_TOKEN",
        "TG_BOT_TOKEN",
        "BOT_TOKEN",
        "ATTENDANCE_RUN_MODE",
        "start_polling",
        "set_webhook",
        "delete_webhook",
        "api.telegram.org",
    )
    violations: list[str] = []
    for path in checked:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="strict")
        if any(value in content for value in forbidden):
            violations.append(str(path.relative_to(_ROOT)))
    assert violations == []


def test_attendance_provider_rejects_telegram_owner_credentials() -> None:
    with pytest.raises(RuntimeError, match="must not receive Telegram owner"):
        assert_no_telegram_owner_credentials(
            {"TELEGRAM_BOT_TOKEN": "forbidden-owner-credential"}
        )

    assert_no_telegram_owner_credentials(
        {
            "GATEWAY_TO_ATTENDANCE_BEARER_TOKEN": "gateway-credential",
            "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN": "provider-credential",
        }
    )
