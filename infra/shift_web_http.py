from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import time
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile

from infra.shift_web_config import current_year_month, load_shift_web_config
from infra.telegram_webapp_auth import tg_user_id_from_init_data, validate_telegram_init_data
from repositories import admin_list_repo, employee_shift_config_repo
from services import shift_import_service, shift_web_session

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "shift_app"
_YM_RE = re.compile(r"^\d{4}-\d{2}$")
_TELEGRAM_CORS_ORIGINS = frozenset(
    {
        "https://web.telegram.org",
        "https://webk.telegram.org",
    }
)


def _download_cors_headers(request: web.Request) -> dict[str, str]:
    """Telegram Mini App downloadFile 要求响应带 CORS（尤其 iOS）。"""
    origin = (request.headers.get("Origin") or "").strip()
    if origin in _TELEGRAM_CORS_ORIGINS or origin.endswith(".telegram.org"):
        allow = origin
    else:
        allow = "https://web.telegram.org"
    return {
        "Access-Control-Allow-Origin": allow,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": (
            "X-Telegram-Init-Data, X-Web-Session, Authorization, X-API-Key, Content-Type"
        ),
    }


def _init_data_from_request(request: web.Request) -> str | None:
    header = (request.headers.get("X-Telegram-Init-Data") or "").strip()
    if header:
        return header
    q = request.query.get("initData") or request.query.get("init_data")
    return str(q).strip() if q else None


def _api_token_from_request(request: web.Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    key = request.headers.get("X-API-Key")
    if key:
        return key.strip() or None
    q = request.query.get("api_token")
    return str(q).strip() if q else None


def _web_session_from_request(request: web.Request) -> str | None:
    header = (request.headers.get("X-Web-Session") or "").strip()
    if header:
        return header
    q = request.query.get("web_session")
    return str(q).strip() if q else None


def _tg_id_from_init_data(request: web.Request) -> int | None:
    init_data = _init_data_from_request(request)
    if not init_data:
        return None
    return _tg_id_from_init_data_raw(request, init_data)


def _require_admin(request: web.Request) -> tuple[int, web.Response | None]:
    """WebApp：优先 initData；URL 里过期的 web_session 不阻断。浏览器开发模式可走 API Key。"""
    cfg = load_shift_web_config()
    if cfg.browser_dev:
        from infra.daily_report_config import load_daily_report_api_config

        expected = load_daily_report_api_config().token
        token = _api_token_from_request(request)
        if expected and token and secrets.compare_digest(token, expected):
            return 0, None

    session = _web_session_from_request(request)
    if session:
        tg_id = shift_web_session.verify_session(session)
        if tg_id is not None:
            if not admin_list_repo.is_admin_by_tg_id(tg_id=tg_id):
                return 0, web.json_response({"ok": False, "message": "无权限操作"}, status=403)
            return tg_id, None

    tg_id = _tg_id_from_init_data(request)
    if tg_id is not None:
        if not admin_list_repo.is_admin_by_tg_id(tg_id=tg_id):
            return 0, web.json_response({"ok": False, "message": "无权限操作"}, status=403)
        return tg_id, None

    if session:
        return 0, web.json_response(
            {
                "ok": False,
                "message": "链接已过期，请在 Telegram 私聊里点底部「班次」重新打开",
                "code": "session_expired",
            },
            status=401,
        )
    return 0, web.json_response(
        {
            "ok": False,
            "message": "请在 Telegram 私聊机器人里点「班次」打开本页",
            "code": "auth_required",
        },
        status=401,
    )


def _parse_time(value: str) -> time | None:
    raw = (value or "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    try:
        if len(parts) == 2:
            return time(int(parts[0]), int(parts[1]))
        if len(parts) == 3:
            return time(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    return None


def _row_to_json(row) -> dict[str, Any]:
    cin = row.shift_checkin_time
    cout = row.shift_checkout_time
    return {
        "id": row.id,
        "year_month": row.year_month,
        "employee_id": row.employee_id,
        "english_name": row.english_name,
        "shift_time_range": row.shift_time_range,
        "shift_checkin_time": cin.strftime("%H:%M:%S") if cin else "",
        "shift_checkout_time": cout.strftime("%H:%M:%S") if cout else "",
        "monthly_rest_days": row.monthly_rest_days or "",
    }


async def _handle_exchange_session(request: web.Request) -> web.Response:
    """用 Telegram initData 换取 web_session（避免部分客户端拿不到 initData 头）。"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "message": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "message": "invalid body"}, status=400)
    init_data = str(body.get("init_data") or body.get("initData") or "").strip()
    if not init_data:
        return web.json_response({"ok": False, "message": "init_data required"}, status=400)
    tg_id = _tg_id_from_init_data_raw(request, init_data)
    if tg_id is None:
        return web.json_response({"ok": False, "message": "invalid init data"}, status=401)
    if not admin_list_repo.is_admin_by_tg_id(tg_id=tg_id):
        return web.json_response({"ok": False, "message": "无权限操作"}, status=403)
    token = shift_web_session.create_session(tg_id=tg_id)
    return web.json_response(
        {"ok": True, "web_session": token},
        headers={"Cache-Control": "no-store"},
    )


def _tg_id_from_init_data_raw(request: web.Request, init_data: str) -> int | None:
    bot: Bot = request.app["bot"]
    parsed = validate_telegram_init_data(init_data=init_data, bot_token=bot.token)
    if not parsed:
        return None
    return tg_user_id_from_init_data(parsed)


async def _handle_list(request: web.Request) -> web.Response:
    _, err = _require_admin(request)
    if err:
        return err
    ym = (request.query.get("year_month") or "").strip()
    if not ym:
        cfg = load_shift_web_config()
        ym = current_year_month(tz_name=cfg.timezone_name)
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    rows = employee_shift_config_repo.list_by_year_month(year_month=ym)
    return web.json_response(
        {"ok": True, "year_month": ym, "rows": [_row_to_json(r) for r in rows]},
        headers={"Cache-Control": "no-store"},
    )


async def _do_send_template(
    request: web.Request, *, tg_id: int, body: dict[str, Any]
) -> web.Response:
    target = int(tg_id) if tg_id else 0
    if not target:
        try:
            target = int(body.get("notify_tg_id") or 0)
        except (TypeError, ValueError):
            target = 0
    if not target:
        return web.json_response(
            {"ok": False, "message": "无法识别 Telegram 用户，请从机器人内打开班次"},
            status=400,
        )
    ym = str(body.get("year_month") or request.query.get("year_month") or "").strip()
    if not ym:
        cfg = load_shift_web_config()
        ym = current_year_month(tz_name=cfg.timezone_name)
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    bot: Bot = request.app["bot"]
    fname = f"shift_template_{ym}.csv"
    data = shift_import_service.template_csv_bytes(year_month=ym)
    try:
        await bot.send_document(
            chat_id=target,
            document=BufferedInputFile(data, filename=fname),
            caption=(
                f"班次导入模板（{ym}）\n"
                "请用 Excel 填写后，在 Web App「上传」中选择该文件导入。"
            ),
        )
    except TelegramForbiddenError:
        log.warning("shift_template forbidden tg_id=%s", target)
        return web.json_response(
            {
                "ok": False,
                "message": "发送失败：请先在私聊对机器人发送 /start，再点下载模板",
            },
            status=403,
        )
    except TelegramBadRequest as e:
        log.warning("shift_template bad request tg_id=%s: %s", target, e)
        return web.json_response(
            {"ok": False, "message": f"发送失败：{e}"},
            status=400,
        )
    except Exception as e:
        log.warning("shift_template send failed tg_id=%s: %s", target, e)
        return web.json_response(
            {"ok": False, "message": f"发送失败：{e}"},
            status=500,
        )
    log.info("shift_template sent to tg_id=%s ym=%s", target, ym)
    return web.json_response({"ok": True, "message": "已发送到您的 Telegram 私聊"})


async def _handle_save(request: web.Request) -> web.Response:
    tg_id, err = _require_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "message": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "message": "invalid body"}, status=400)
    action = str(body.get("action") or "").strip()
    if action == "send_template":
        return await _do_send_template(request, tg_id=tg_id, body=body)
    if action == "send_export":
        return await _do_send_export(request, tg_id=tg_id, body=body)
    ym = str(body.get("year_month") or "").strip()
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    items = body.get("rows")
    if not isinstance(items, list):
        return web.json_response({"ok": False, "message": "rows required"}, status=400)

    saved, ym_out, errors = shift_import_service.import_row_dicts(
        rows=items,
        default_year_month=ym,
    )
    if errors:
        return web.json_response(
            {"ok": False, "message": "；".join(errors[:5]), "errors": errors},
            status=400,
        )
    return web.json_response({"ok": True, "saved": saved, "year_month": ym_out})


async def _do_send_export(
    request: web.Request, *, tg_id: int, body: dict[str, Any]
) -> web.Response:
    target = int(tg_id) if tg_id else 0
    if not target:
        try:
            target = int(body.get("notify_tg_id") or 0)
        except (TypeError, ValueError):
            target = 0
    if not target:
        return web.json_response(
            {"ok": False, "message": "无法识别 Telegram 用户，请从机器人内打开班次"},
            status=400,
        )
    ym = str(body.get("year_month") or request.query.get("year_month") or "").strip()
    if not ym:
        cfg = load_shift_web_config()
        ym = current_year_month(tz_name=cfg.timezone_name)
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    rows = employee_shift_config_repo.list_by_year_month(year_month=ym)
    bot: Bot = request.app["bot"]
    fname = f"shift_export_{ym}.csv"
    data = shift_import_service.encode_shift_config_csv(year_month=ym, rows=rows)
    try:
        await bot.send_document(
            chat_id=target,
            document=BufferedInputFile(data, filename=fname),
            caption=f"班次配置导出（{ym}），共 {len(rows)} 条",
        )
    except TelegramForbiddenError:
        return web.json_response(
            {
                "ok": False,
                "message": "发送失败：请先在私聊对机器人发送 /start，再点导出",
            },
            status=403,
        )
    except TelegramBadRequest as e:
        return web.json_response({"ok": False, "message": f"发送失败：{e}"}, status=400)
    except Exception as e:
        log.warning("shift_export send failed tg_id=%s: %s", target, e)
        return web.json_response({"ok": False, "message": f"发送失败：{e}"}, status=500)
    log.info("shift_export sent to tg_id=%s ym=%s rows=%s", target, ym, len(rows))
    return web.json_response({"ok": True, "message": "已发送到您的 Telegram 私聊"})


async def _handle_send_template(request: web.Request) -> web.Response:
    """将 CSV 模板发到管理员 Telegram 私聊（iOS 最可靠的下载方式）。"""
    tg_id, err = _require_admin(request)
    if err:
        return err
    try:
        raw = await request.read()
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    return await _do_send_template(request, tg_id=tg_id, body=body)


async def _handle_send_export(request: web.Request) -> web.Response:
    """将当月班次配置 CSV 发到管理员 Telegram 私聊。"""
    tg_id, err = _require_admin(request)
    if err:
        return err
    try:
        raw = await request.read()
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    return await _do_send_export(request, tg_id=tg_id, body=body)


async def _handle_export_csv(request: web.Request) -> web.Response:
    _, err = _require_admin(request)
    if err:
        for k, v in _download_cors_headers(request).items():
            err.headers[k] = v
        return err
    ym = (request.query.get("year_month") or "").strip()
    if not ym:
        cfg = load_shift_web_config()
        ym = current_year_month(tz_name=cfg.timezone_name)
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    rows = employee_shift_config_repo.list_by_year_month(year_month=ym)
    body = shift_import_service.encode_shift_config_csv(year_month=ym, rows=rows)
    fname = f"shift_export_{ym}.csv"
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{fname}"',
        **_download_cors_headers(request),
    }
    return web.Response(body=body, headers=headers)


async def _handle_template_options(request: web.Request) -> web.Response:
    return web.Response(status=204, headers=_download_cors_headers(request))


async def _handle_template(request: web.Request) -> web.Response:
    _, err = _require_admin(request)
    if err:
        for k, v in _download_cors_headers(request).items():
            err.headers[k] = v
        return err
    ym = (request.query.get("year_month") or "").strip()
    if not ym:
        cfg = load_shift_web_config()
        ym = current_year_month(tz_name=cfg.timezone_name)
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    body = shift_import_service.template_csv_bytes(year_month=ym)
    fname = f"shift_template_{ym}.csv"
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{fname}"',
        **_download_cors_headers(request),
    }
    return web.Response(body=body, headers=headers)


async def _handle_import_batch(request: web.Request) -> web.Response:
    _, err = _require_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "message": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "message": "invalid body"}, status=400)
    ym = str(body.get("year_month") or "").strip()
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    items = body.get("rows")
    if not isinstance(items, list) or not items:
        return web.json_response({"ok": False, "message": "rows required"}, status=400)
    saved, ym_out, errors = shift_import_service.import_row_dicts(
        rows=items,
        default_year_month=ym,
        force_year_month=True,
    )
    if errors:
        return web.json_response(
            {"ok": False, "message": "；".join(errors[:8]), "errors": errors},
            status=400,
        )
    listed = employee_shift_config_repo.list_by_year_month(year_month=ym_out)
    return web.json_response(
        {
            "ok": True,
            "saved": saved,
            "year_month": ym_out,
            "rows": [_row_to_json(r) for r in listed],
        },
        headers={"Cache-Control": "no-store"},
    )


async def _handle_index(_request: web.Request) -> web.Response:
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        return web.Response(text="shift app not found", status=404)
    return web.FileResponse(index)


def register_shift_web_routes(app: web.Application) -> None:
    app.router.add_get("/shift-app/", _handle_index)
    app.router.add_get("/shift-app/index.html", _handle_index)
    app.router.add_get("/api/v1/shift-config", _handle_list)
    app.router.add_post("/api/v1/shift-config/exchange-session", _handle_exchange_session)
    app.router.add_route("OPTIONS", "/api/v1/shift-config/template", _handle_template_options)
    app.router.add_get("/api/v1/shift-config/template", _handle_template)
    app.router.add_post("/api/v1/shift-config", _handle_save)
    app.router.add_post("/api/v1/shift-config/import-batch", _handle_import_batch)
    app.router.add_post("/api/v1/shift-config/send-template", _handle_send_template)
    app.router.add_post("/api/v1/shift-config/template/send", _handle_send_template)
    app.router.add_post("/api/v1/shift-config/send-export", _handle_send_export)
    app.router.add_get("/api/v1/shift-config/export", _handle_export_csv)
    log.info("shift_web: send-template routes registered")
