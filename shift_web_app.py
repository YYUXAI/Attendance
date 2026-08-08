from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web

from gateway_provider.runtime_security import assert_no_telegram_owner_credentials
from gateway_provider.webapp_session import GatewayWebAppSessionVerifier
from infra.db import get_cursor
from infra.db import database_url_scope
from infra.logger import configure_logging
from infra.shift_web_http import (
    SHIFT_WEB_SESSION_VERIFIER_KEY,
    register_shift_web_routes,
)


log = logging.getLogger("attendance-shift-web")


def _database_ready() -> bool:
    try:
        with get_cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.execute("SELECT 1 FROM public.admin_list LIMIT 1")
            cursor.execute("SELECT 1 FROM public.employee_shift_config LIMIT 1")
        return True
    except Exception:  # noqa: BLE001
        log.exception("shift web database readiness failed")
        return False


async def _health(_request: web.Request) -> web.Response:
    database_ready = await asyncio.to_thread(_database_ready)
    return web.json_response(
        {
            "ok": database_ready,
            "service": "UX助手考勤班表",
            "components": {
                "http": True,
                "database": database_ready,
                "polling": False,
                "workers": False,
            },
        },
        status=200 if database_ready else 503,
        headers={"Cache-Control": "no-store"},
    )


def create_shift_web_app(
    *,
    database_url: str,
    gateway_session_signing_secret: str,
) -> web.Application:
    resolved_database_url = database_url.strip()
    if not resolved_database_url:
        raise ValueError("database_url is required")

    @web.middleware
    async def database_scope(
        request: web.Request,
        handler: web.RequestHandler,
    ) -> web.StreamResponse:
        with database_url_scope(resolved_database_url):
            return await handler(request)

    app = web.Application(middlewares=[database_scope])
    app[SHIFT_WEB_SESSION_VERIFIER_KEY] = GatewayWebAppSessionVerifier(
        signing_secret=gateway_session_signing_secret,
        audience="ATTENDANCE",
    )
    app.router.add_get("/healthz", _health)
    register_shift_web_routes(app)
    return app


def _required_environment(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    assert_no_telegram_owner_credentials(os.environ)
    configure_logging()
    host = (os.getenv("SHIFT_WEB_HOST") or "127.0.0.1").strip()
    port = int((os.getenv("SHIFT_WEB_PORT") or "19084").strip())
    app = create_shift_web_app(
        database_url=_required_environment("ATTENDANCE_DATABASE_URL"),
        gateway_session_signing_secret=_required_environment(
            "GATEWAY_WEBAPP_SESSION_SIGNING_SECRET"
        ),
    )
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
