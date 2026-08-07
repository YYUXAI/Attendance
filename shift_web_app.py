from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot
from dotenv import load_dotenv

from infra.bot_owner import load_attendance_bot_owner
from infra.db import get_cursor
from infra.logger import configure_logging
from infra.shift_web_http import SHIFT_WEB_BOT_KEY, register_shift_web_routes


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


def create_shift_web_app(*, bot: Bot) -> web.Application:
    app = web.Application()
    app[SHIFT_WEB_BOT_KEY] = bot
    app.router.add_get("/healthz", _health)
    register_shift_web_routes(app)

    async def close_bot_session(_app: web.Application) -> None:
        await bot.session.close()

    app.on_cleanup.append(close_bot_session)
    return app


def resolve_shift_web_bot_token() -> str:
    owner = load_attendance_bot_owner()
    dedicated = (os.getenv("SHIFT_WEB_TELEGRAM_BOT_TOKEN") or "").strip()
    if owner == "ux_assistant":
        if not dedicated:
            raise RuntimeError(
                "SHIFT_WEB_TELEGRAM_BOT_TOKEN is required for UX助手 Shift Web"
            )
        return dedicated
    return dedicated or (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def main() -> None:
    load_dotenv(
        override=(os.getenv("ATTENDANCE_DOTENV_OVERRIDE") or "1").strip() != "0",
        encoding="utf-8",
    )
    configure_logging()
    token = resolve_shift_web_bot_token()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
    host = (os.getenv("SHIFT_WEB_HOST") or "127.0.0.1").strip()
    port = int((os.getenv("SHIFT_WEB_PORT") or "18084").strip())
    app = create_shift_web_app(bot=Bot(token=token))
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
