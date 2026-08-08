from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from aiohttp import web

from gateway_provider.webapp_session import (
    GatewayWebAppSessionVerifier,
    InvalidGatewayWebAppSessionError,
)
from gateway_provider.webapp_session_store import (
    AttendanceWebAppSessionStore,
    InvalidAttendanceWebAppSessionError,
    ReplayedGatewayWebAppSessionError,
)
from infra.shift_web_config import current_year_month, load_shift_web_config
from repositories import admin_list_repo, employee_shift_config_repo
from services import shift_import_service
from services.shift_view_service import filter_shift_config_rows, shift_view_for_tg_id
from services.employee_shift_day_service import load_calendar_map
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "shift_app"
SHIFT_WEB_SESSION_VERIFIER_KEY: web.AppKey[GatewayWebAppSessionVerifier] = (
    web.AppKey("shift_web_session_verifier", GatewayWebAppSessionVerifier)
)
SHIFT_WEB_PROVIDER_SESSION_STORE_KEY: web.AppKey[AttendanceWebAppSessionStore] = (
    web.AppKey("shift_web_provider_session_store", AttendanceWebAppSessionStore)
)
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
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
    }


def _require_admin(request: web.Request) -> tuple[int, web.Response | None]:
    """只接受由 Attendance 自身 admin_list 授权的管理员。"""
    token = _bearer_token(request)
    if token is None:
        return 0, web.json_response(
            {
                "ok": False,
                "code": "SESSION_INVALID",
                "message": "会话无效，请重新打开班表。",
            },
            status=401,
        )
    try:
        tg_id = request.app[SHIFT_WEB_PROVIDER_SESSION_STORE_KEY].authenticate(token)
    except InvalidAttendanceWebAppSessionError:
        return 0, web.json_response(
            {
                "ok": False,
                "code": "SESSION_INVALID",
                "message": "会话无效，请重新打开班表。",
            },
            status=401,
        )
    if not admin_list_repo.is_admin_by_tg_id(tg_id=tg_id):
        return 0, web.json_response(
            {"ok": False, "code": "FORBIDDEN", "message": "无权限操作"},
            status=403,
        )
    return tg_id, None


def _bearer_token(request: web.Request) -> str | None:
    authorization = (request.headers.get("Authorization") or "").strip()
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


async def _handle_gateway_session_exchange(request: web.Request) -> web.Response:
    token = _bearer_token(request)
    if token is None:
        return web.json_response(
            {
                "ok": False,
                "code": "SESSION_INVALID",
                "message": "Gateway 会话无效，请重新打开班表。",
            },
            status=401,
        )
    try:
        principal = request.app[SHIFT_WEB_SESSION_VERIFIER_KEY].verify(token)
        issued = request.app[SHIFT_WEB_PROVIDER_SESSION_STORE_KEY].exchange(
            principal
        )
    except InvalidGatewayWebAppSessionError:
        return web.json_response(
            {
                "ok": False,
                "code": "SESSION_INVALID",
                "message": "Gateway 会话无效，请重新打开班表。",
            },
            status=401,
        )
    except ReplayedGatewayWebAppSessionError:
        return web.json_response(
            {
                "ok": False,
                "code": "SESSION_REPLAYED",
                "message": "Gateway 会话已使用，请重新打开班表。",
            },
            status=409,
        )
    return web.json_response(
        {
            "ok": True,
            "tokenType": "Bearer",
            "sessionToken": issued.session_token,
            "expiresAt": issued.expires_at.isoformat().replace("+00:00", "Z"),
        },
        headers={"Cache-Control": "no-store"},
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


def _calendar_display_by_employee(
    *,
    year_month: str,
    employee_ids: list[str],
    as_of: date,
) -> dict[str, dict[str, Any]]:
    """从 Google 同步的日班表生成列表展示字段（今日班次 + 是否多班次）。"""
    if not employee_ids:
        return {}
    cal_map = load_calendar_map(year_month=year_month, employee_ids=employee_ids)
    by_emp: dict[str, list[tuple[date, object]]] = {eid: [] for eid in employee_ids}
    ym_prefix = str(year_month)
    for (eid, wd), ds in cal_map.items():
        if wd.strftime("%Y-%m") != ym_prefix:
            continue
        by_emp.setdefault(eid, []).append((wd, ds))

    out: dict[str, dict[str, Any]] = {}
    for eid in employee_ids:
        entries = sorted(by_emp.get(eid, []), key=lambda x: x[0])
        codes: list[str] = []
        seen: set[str] = set()
        for _, ds in entries:
            if ds.is_rest or not ds.shift_code:
                continue
            if ds.shift_code not in seen:
                seen.add(ds.shift_code)
                codes.append(ds.shift_code)

        today = cal_map.get((eid, as_of))
        today_range = ""
        today_cin = ""
        today_cout = ""
        today_code = ""
        if today is not None:
            if today.is_rest:
                today_range = "月休"
            else:
                today_range = today.shift_time_range
                today_code = today.shift_code
                today_cin = today.checkin.strftime("%H:%M:%S")
                today_cout = today.checkout.strftime("%H:%M:%S")

        codes_str = "→".join(codes) if len(codes) > 1 else (codes[0] if codes else "")
        if today_range == "月休":
            display_shift = "月休"
            display_checkin = ""
            display_checkout = ""
        elif today_range:
            display_shift = (
                f"{codes_str} · 今日{today_code} {today_range}"
                if codes_str and len(codes) > 1
                else today_range
            )
            display_checkin = today_cin
            display_checkout = today_cout
        elif codes_str:
            display_shift = codes_str
            display_checkin = ""
            display_checkout = ""
        else:
            display_shift = ""
            display_checkin = ""
            display_checkout = ""

        out[eid] = {
            "calendar_shift_codes": codes_str,
            "calendar_shift_time_range": today_range,
            "calendar_checkin": today_cin,
            "calendar_checkout": today_cout,
            "calendar_today_code": today_code,
            "has_multiple_shifts": len(codes) > 1,
            "display_shift": display_shift,
            "display_checkin": display_checkin,
            "display_checkout": display_checkout,
        }
    return out


def _rows_to_json(
    rows,
    *,
    year_month: str,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    cfg = load_shift_web_config()
    ref = as_of or datetime.now(ZoneInfo(cfg.timezone_name)).date()
    cal = _calendar_display_by_employee(
        year_month=year_month,
        employee_ids=[str(r.employee_id) for r in rows],
        as_of=ref,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_json(row)
        item.update(cal.get(str(row.employee_id), {}))
        out.append(item)
    return out


async def _handle_list(request: web.Request) -> web.Response:
    tg_id, err = _require_admin(request)
    if err:
        return err
    ym = (request.query.get("year_month") or "").strip()
    if not ym:
        cfg = load_shift_web_config()
        ym = current_year_month(tz_name=cfg.timezone_name)
    if not _YM_RE.match(ym):
        return web.json_response({"ok": False, "message": "invalid year_month"}, status=400)
    rows = employee_shift_config_repo.list_by_year_month(year_month=ym)
    view = shift_view_for_tg_id(tg_id=tg_id)
    rows = filter_shift_config_rows(rows=rows, year_month=ym, view=view)
    cfg = load_shift_web_config()
    as_of = datetime.now(ZoneInfo(cfg.timezone_name)).date()
    return web.json_response(
        {
            "ok": True,
            "year_month": ym,
            "display_date": as_of.isoformat(),
            "rows": _rows_to_json(rows, year_month=ym, as_of=as_of),
        },
        headers={"Cache-Control": "no-store"},
    )


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


async def _handle_export_csv(request: web.Request) -> web.Response:
    tg_id, err = _require_admin(request)
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
    view = shift_view_for_tg_id(tg_id=tg_id)
    rows = filter_shift_config_rows(rows=rows, year_month=ym, view=view)
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
    cfg = load_shift_web_config()
    as_of = datetime.now(ZoneInfo(cfg.timezone_name)).date()
    return web.json_response(
        {
            "ok": True,
            "saved": saved,
            "year_month": ym_out,
            "display_date": as_of.isoformat(),
            "rows": _rows_to_json(listed, year_month=ym_out, as_of=as_of),
        },
        headers={"Cache-Control": "no-store"},
    )


_ICON_NAMES = frozenset({"download.png", "upload.png"})


async def _handle_icon(request: web.Request) -> web.Response:
    name = request.match_info.get("name", "")
    if name not in _ICON_NAMES:
        return web.Response(status=404)
    path = _STATIC_DIR / "icons" / name
    if not path.is_file():
        return web.Response(status=404)
    return web.FileResponse(path)


async def _handle_index(_request: web.Request) -> web.Response:
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        return web.Response(text="shift app not found", status=404)
    return web.FileResponse(index, headers={"Cache-Control": "no-store, max-age=0"})


def register_shift_web_routes(app: web.Application) -> None:
    app.router.add_get("/shift-app/", _handle_index)
    app.router.add_get("/shift-app/index.html", _handle_index)
    app.router.add_get("/shift-app/icons/{name}", _handle_icon)
    app.router.add_post(
        "/api/v1/webapp/session/exchange",
        _handle_gateway_session_exchange,
    )
    app.router.add_get("/api/v1/shift-config", _handle_list)
    app.router.add_route("OPTIONS", "/api/v1/shift-config/template", _handle_template_options)
    app.router.add_get("/api/v1/shift-config/template", _handle_template)
    app.router.add_post("/api/v1/shift-config", _handle_save)
    app.router.add_post("/api/v1/shift-config/import-batch", _handle_import_batch)
    app.router.add_get("/api/v1/shift-config/export", _handle_export_csv)
    log.info("shift_web: Gateway session routes registered")
