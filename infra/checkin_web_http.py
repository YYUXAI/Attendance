from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from aiogram import Bot

from domain.shared.result import ServiceResult
from services import checkin_web_session
from services.checkin_web_submit_service import build_context, submit_checkin_from_web

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "checkin_app"


def _session_from_request(request: web.Request) -> str | None:
    header = (request.headers.get("X-Web-Session") or "").strip()
    if header:
        return header
    q = request.query.get("web_session")
    return str(q).strip() if q else None


def _verify_session(request: web.Request) -> tuple[int, str] | web.Response:
    token = _session_from_request(request)
    if not token:
        return web.json_response({"ok": False, "message": "缺少会话，请回到 Telegram 重新点「签到/签退」"}, status=401)
    parsed = checkin_web_session.verify_session(token)
    if not parsed:
        return web.json_response({"ok": False, "message": "会话已过期，请重新打开打卡页"}, status=401)
    return parsed


async def _handle_index(_request: web.Request) -> web.Response:
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        return web.Response(text="checkin app not found", status=404)
    return web.FileResponse(index)


async def _handle_context(request: web.Request) -> web.Response:
    verified = _verify_session(request)
    if isinstance(verified, web.Response):
        return verified
    tg_id, action = verified
    ctx_or_err = build_context(tg_id=tg_id, action=action)
    if isinstance(ctx_or_err, ServiceResult):
        return web.json_response({"ok": False, "message": ctx_or_err.message}, status=400)
    ctx = ctx_or_err
    return web.json_response(
        {
            "ok": True,
            "english_name": ctx.english_name,
            "employee_id": ctx.employee_id,
            "action": ctx.action,
            "shift_time_range": ctx.shift_time_range,
            "shift_checkin": ctx.shift_checkin,
            "shift_checkout": ctx.shift_checkout,
            "group_id": ctx.group_id,
        }
    )


async def _handle_submit(request: web.Request) -> web.Response:
    verified = _verify_session(request)
    if isinstance(verified, web.Response):
        return verified
    tg_id, action = verified

    reader = await request.multipart()
    image_bytes: bytes | None = None
    filename = "checkin.jpg"
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "image":
            filename = part.filename or "checkin.jpg"
            image_bytes = await part.read(decode=True)
    if not image_bytes:
        return web.json_response({"ok": False, "message": "请上传图片"}, status=400)

    bot: Bot = request.app["bot"]
    result = await submit_checkin_from_web(
        bot=bot,
        tg_id=tg_id,
        action=action,
        image_bytes=image_bytes,
        filename=filename,
    )
    status = 200 if result.ok else 400
    return web.json_response({"ok": result.ok, "message": result.message}, status=status)


def register_checkin_web_routes(app: web.Application) -> None:
    app.router.add_get("/checkin-app/", _handle_index)
    app.router.add_get("/checkin-app/index.html", _handle_index)
    app.router.add_get("/api/v1/checkin/context", _handle_context)
    app.router.add_post("/api/v1/checkin/submit", _handle_submit)
