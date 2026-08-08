from __future__ import annotations

import ast
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
_NON_PRODUCTION_PARTS = frozenset({".git", ".gitnexus", ".venv", "__pycache__"})


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
            if any(name == "aiogram" or name.startswith("aiogram.") for name in imported):
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
    assert "aiogram" not in requirements.lower()


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
