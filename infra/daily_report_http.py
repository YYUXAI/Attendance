from __future__ import annotations

import asyncio
import json
import logging
import secrets
from pathlib import Path
from typing import Any, Optional

from aiohttp import web
from aiogram import Bot

from infra.daily_report_config import load_daily_report_api_config, load_daily_report_config
from infra.google_sheets_config import load_google_sheets_config
from infra.checkin_web_http import register_checkin_web_routes
from infra.shift_web_config import load_shift_web_config
from infra.shift_web_http import register_shift_web_routes
from services.google_sheets_shift_sync_service import sync_shifts_from_google_sheets
from services.daily_attendance_report_send import (
    outcome_to_json,
    parse_report_date_arg,
    send_daily_attendance_report,
)

log = logging.getLogger(__name__)

# 与 23:00 定时任务发送的群打卡 CSV 为同一逻辑
SEND_PATH = "/api/v1/group-checkin-csv/send"
LEGACY_SEND_PATH = "/api/v1/daily-attendance-report/send"
HEALTH_PATH = "/health"
DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
PHASE2_PRD_PATH = "/docs/phase2-prd-figma.html"
GOOGLE_SHEETS_SYNC_PATH = "/api/v1/google-sheets/shift-sync"


def _extract_token(request: web.Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    key = request.headers.get("X-API-Key")
    if key:
        return key.strip() or None
    q = request.query.get("token")
    if q:
        return str(q).strip() or None
    return None


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not str(value).strip():
        return default
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


async def _read_json_body(request: web.Request) -> dict[str, Any]:
    if request.content_type != "application/json":
        return {}
    try:
        raw = await request.read()
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _merge_params(request: web.Request, body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("date", "force", "record_sent", "notify_tg_id"):
        if key in request.query:
            out[key] = request.query.get(key)
    for key, val in body.items():
        if key in ("date", "force", "record_sent", "notify_tg_id"):
            out[key] = val
    return out


async def _handle_send(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    api_cfg = request.app["api_cfg"]
    token = _extract_token(request)
    if not api_cfg.token or not token or not secrets.compare_digest(token, api_cfg.token):
        return web.json_response({"ok": False, "message": "unauthorized"}, status=401)

    body = await _read_json_body(request)
    params = _merge_params(request, body)
    cfg = load_daily_report_config()

    try:
        report_date = parse_report_date_arg(
            str(params["date"]) if params.get("date") is not None else None,
            tz_name=cfg.timezone_name,
        )
    except ValueError as e:
        return web.json_response({"ok": False, "message": str(e)}, status=400)

    force = _parse_bool(
        str(params["force"]) if params.get("force") is not None else None,
        default=True,
    )
    record_sent = _parse_bool(
        str(params["record_sent"]) if params.get("record_sent") is not None else None,
        default=False,
    )

    notify_tg_id: Optional[int] = None
    raw_nid = params.get("notify_tg_id")
    if raw_nid is not None and str(raw_nid).strip():
        try:
            notify_tg_id = int(str(raw_nid).strip())
        except ValueError:
            return web.json_response({"ok": False, "message": "invalid notify_tg_id"}, status=400)

    try:
        outcome = await send_daily_attendance_report(
            bot=bot,
            report_date=report_date,
            notify_tg_id=notify_tg_id,
            force=force,
            record_sent=record_sent,
            cfg=cfg,
        )
    except Exception as e:
        log.exception("daily_report_api: send failed")
        return web.json_response({"ok": False, "message": str(e)}, status=500)

    status = 200 if outcome.ok else 400
    return web.json_response(outcome_to_json(outcome), status=status)


async def _handle_google_sheets_sync(request: web.Request) -> web.Response:
    api_cfg = request.app["api_cfg"]
    token = _extract_token(request)
    if not api_cfg.token or not token or not secrets.compare_digest(token, api_cfg.token):
        return web.json_response({"ok": False, "message": "unauthorized"}, status=401)

    body = await _read_json_body(request)
    year_month = request.query.get("year_month") or body.get("year_month")
    try:
        result = await asyncio.to_thread(
            sync_shifts_from_google_sheets,
            year_month=str(year_month).strip() if year_month else None,
        )
    except Exception as e:
        log.exception("google_sheets_api: sync failed")
        return web.json_response({"ok": False, "message": str(e)}, status=500)

    status = 200 if result.ok else 400
    return web.json_response(
        {
            "ok": result.ok,
            "message": result.message,
            "year_month": result.year_month,
            "employee_count": result.employee_count,
            "calendar_cells": result.calendar_cells,
            "sheet_title": result.sheet_title,
        },
        status=status,
    )


async def _handle_health(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "service": "group_checkin_csv",
            "send_path": SEND_PATH,
            "phase2_prd": PHASE2_PRD_PATH,
        }
    )


async def _handle_phase2_prd(_request: web.Request) -> web.Response:
    path = DOCS_DIR / "phase2-prd-figma.html"
    if not path.is_file():
        raise web.HTTPNotFound(text="phase2-prd-figma.html not found")
    return web.FileResponse(path)


def create_app(*, bot: Bot) -> web.Application:
    api_cfg = load_daily_report_api_config()
    shift_cfg = load_shift_web_config()
    app = web.Application()
    app["bot"] = bot
    app["api_cfg"] = api_cfg
    app.router.add_get(HEALTH_PATH, _handle_health)
    app.router.add_get(PHASE2_PRD_PATH, _handle_phase2_prd)
    for path in (SEND_PATH, LEGACY_SEND_PATH):
        app.router.add_get(path, _handle_send)
        app.router.add_post(path, _handle_send)
    if shift_cfg.enabled:
        register_shift_web_routes(app)
        register_checkin_web_routes(app)
    if load_google_sheets_config().enabled:
        app.router.add_get(GOOGLE_SHEETS_SYNC_PATH, _handle_google_sheets_sync)
        app.router.add_post(GOOGLE_SHEETS_SYNC_PATH, _handle_google_sheets_sync)
    return app


async def run_daily_report_http_server(*, bot: Bot) -> None:
    api_cfg = load_daily_report_api_config()
    shift_cfg = load_shift_web_config()
    if not api_cfg.enabled and not shift_cfg.enabled:
        log.info("http_server: disabled (API and shift web both off)")
        return
    if api_cfg.enabled and not api_cfg.token:
        log.warning(
            "http_server: DAILY_ATTENDANCE_REPORT_API_TOKEN empty — CSV API disabled; shift web may still run"
        )

    app = create_app(bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=api_cfg.host, port=api_cfg.port)
    await site.start()
    log.info(
        "http_server: listening http://%s:%s (csv=%s shift=%s)",
        api_cfg.host,
        api_cfg.port,
        api_cfg.enabled,
        shift_cfg.enabled,
    )
    stop = asyncio.Event()
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
