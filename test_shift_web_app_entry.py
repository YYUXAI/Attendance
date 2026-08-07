from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from infra import shift_web_http
from shift_web_app import create_shift_web_app, resolve_shift_web_bot_token


def test_shift_web_entry_exposes_only_shift_and_truthful_health_routes() -> None:
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    app = create_shift_web_app(bot=bot)
    paths = {resource.canonical for resource in app.router.resources()}

    assert "/healthz" in paths
    assert "/shift-app/" in paths
    assert "/api/v1/shift-config" in paths
    assert not any("checkin-app" in path for path in paths)
    assert not any("daily-attendance-report" in path for path in paths)

    asyncio.run(app.cleanup())


def test_shift_web_entry_never_starts_polling_or_workers() -> None:
    source = (Path(__file__).parent / "shift_web_app.py").read_text(encoding="utf-8")

    assert "prepare_runtime" not in source
    assert "start_polling" not in source
    assert "run_notification_worker" not in source
    assert "run_audit_worker" not in source


def test_shift_web_entry_supports_process_local_bot_token_isolation() -> None:
    source = Path("shift_web_app.py").read_text(encoding="utf-8")

    assert "SHIFT_WEB_TELEGRAM_BOT_TOKEN" in source
    assert "ATTENDANCE_DOTENV_OVERRIDE" in source


def test_unified_shift_web_requires_its_dedicated_bot_token(monkeypatch) -> None:
    monkeypatch.setenv("ATTENDANCE_BOT_OWNER", "ux_assistant")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.delenv("SHIFT_WEB_TELEGRAM_BOT_TOKEN", raising=False)

    try:
        resolve_shift_web_bot_token()
    except RuntimeError as exc:
        assert "SHIFT_WEB_TELEGRAM_BOT_TOKEN" in str(exc)
    else:
        raise AssertionError("unified Shift Web accepted the legacy Attendance token")

    monkeypatch.setenv("SHIFT_WEB_TELEGRAM_BOT_TOKEN", "unified-token")
    assert resolve_shift_web_bot_token() == "unified-token"


def test_shift_web_has_one_http_route_owner() -> None:
    root = Path(__file__).parent

    assert not (root / "shift_web_http.py").exists()
    assert (root / "infra" / "shift_web_http.py").is_file()


def test_send_template_route_passes_authenticated_admin_id(monkeypatch) -> None:
    class Request:
        async def read(self):
            return b"{}"

    observed = {}

    async def send_template(_request, *, tg_id, body):
        observed.update(tg_id=tg_id, body=body)
        return object()

    monkeypatch.setattr(shift_web_http, "_require_admin", lambda _request: (42, None))
    monkeypatch.setattr(shift_web_http, "_do_send_template", send_template)

    asyncio.run(shift_web_http._handle_send_template(Request()))

    assert observed == {"tg_id": 42, "body": {}}
