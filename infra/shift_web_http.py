from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile

from infra.shift_web_config import current_year_month, load_shift_web_config
from infra.log_redaction import redacted_ref
from infra.telegram_webapp_auth import tg_user_id_from_init_data, validate_telegram_init_data
from repositories import admin_list_repo, employee_shift_config_repo
from services import shift_import_service, shift_web_session
from services.shift_view_service import filter_shift_config_rows, shift_view_for_tg_id
from services.employee_shift_day_service import load_calendar_map
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "shift_app"
SHIFT_WEB_BOT_KEY: web.AppKey[Bot] = web.AppKey("shift_web_bot", Bot)
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
    return header or None


def _web_session_from_request(request: web.Request) -> str | None:
    header = (request.headers.get("X-Web-Session") or "").strip()
    return header or None


def _tg_id_from_init_data(request: web.Request) -> int | None:
    init_data = _init_data_from_request(request)
    if not init_data:
        return None
    return _tg_id_from_init_data_raw(request, init_data)


def _require_admin(request: web.Request) -> tuple[int, web.Response | None]:
    """只接受由 Attendance 自身 admin_list 授权的管理员。"""
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
                "message": "链接已过期，请在 Telegram 私聊里点「班表」重新打开",
                "code": "session_expired",
            },
            status=401,
        )
    return 0, web.json_response(
        {
            "ok": False,
            "message": "请在 Telegram 私聊机器人里点「班表」打开本页",
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
    bot: Bot = request.app.get(SHIFT_WEB_BOT_KEY) or request.app["bot"]
    parsed = validate_telegram_init_data(init_data=init_data, bot_token=bot.token)
    if not parsed:
        return None
    return tg_user_id_from_init_data(parsed)


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
    bot: Bot = request.app.get(SHIFT_WEB_BOT_KEY) or request.app["bot"]
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
        log.warning("shift_template forbidden tg_ref=%s", redacted_ref(target))
        return web.json_response(
            {
                "ok": False,
                "message": "发送失败：请先在私聊对机器人发送 /start，再点下载模板",
            },
            status=403,
        )
    except TelegramBadRequest:
        log.warning("shift_template bad request tg_ref=%s", redacted_ref(target))
        return web.json_response(
            {"ok": False, "message": "发送失败：Telegram 未接受该文件，请稍后重试。"},
            status=400,
        )
    except Exception:
        log.exception("shift_template send failed tg_ref=%s", redacted_ref(target))
        return web.json_response(
            {"ok": False, "message": "发送失败，请稍后重试。"},
            status=500,
        )
    log.info("shift_template sent tg_ref=%s ym=%s", redacted_ref(target), ym)
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
    view = shift_view_for_tg_id(tg_id=target)
    rows = filter_shift_config_rows(rows=rows, year_month=ym, view=view)
    bot: Bot = request.app.get(SHIFT_WEB_BOT_KEY) or request.app["bot"]
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
    except TelegramBadRequest:
        log.warning("shift_export bad request tg_ref=%s", redacted_ref(target))
        return web.json_response(
            {"ok": False, "message": "发送失败：Telegram 未接受该文件，请稍后重试。"},
            status=400,
        )
    except Exception:
        log.exception("shift_export send failed tg_ref=%s", redacted_ref(target))
        return web.json_response(
            {"ok": False, "message": "发送失败，请稍后重试。"},
            status=500,
        )
    log.info(
        "shift_export sent tg_ref=%s ym=%s rows=%s",
        redacted_ref(target),
        ym,
        len(rows),
    )
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
