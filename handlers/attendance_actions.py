from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    Message,
    WebAppInfo,
)

from infra.daily_report_config import load_daily_report_config
from keyboards.actions_menu import build_shift_web_app_url_for_admin
from keyboards.actions_menu import reply_group_single_fill_menu
from repositories import (
    admin_list_repo,
    registrations_repo,
    temporary_leave_records_repo,
)
from services import attendance_export_service, checkin_service

router = Router()
log = logging.getLogger(__name__)

_GROUP_CHAT = F.chat.type.in_({"group", "supergroup"})

_ACTION_CB = {
    "act:signin": "signin",
    "act:signout": "signout",
    "act:leave": "leave",
    "act:back": "back",
}

def _require_user(message: Message):
    return message.from_user


def _reason_from_leave_message(text: str | None) -> str:
    """从离岗/返岗模板正文提取「原因：」后用户填写内容。"""
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("原因：") or s.startswith("原因:"):
            return s.split("：", 1)[-1].split(":", 1)[-1].strip()[:500]
    return (text or "").strip()[:500]


def _format_leave_duration_minutes(mins: int) -> str:
    if mins < 60:
        return f"{mins}分钟"
    hours, rem = divmod(int(mins), 60)
    if rem:
        return f"{hours}小时{rem}分钟"
    return f"{hours}小时"


def _user_context(*, tg_id: int):
    reg = registrations_repo.get_by_tg_id(int(tg_id))
    if not reg:
        return None, "请先私聊机器人完成注册（英文名$工号）。"
    name = (reg.english_name or "").strip() or "未命名"
    return reg, name


@router.inline_query()
async def inline_query_for_fill_input(inline_query: InlineQuery) -> None:
    """支持「填入输入框」按钮把草稿写入输入栏。"""
    await inline_query.answer([], cache_time=1, is_personal=True)


@router.callback_query(F.data.in_(_ACTION_CB.keys()))
async def group_action_callback(callback: CallbackQuery) -> None:
    """消息内 callback 按钮（未注册兜底）。"""
    await callback.answer()
    if callback.message is None:
        return
    action = _ACTION_CB.get(callback.data or "")
    if not action:
        return
    await reply_group_single_fill_menu(
        message=callback.message,
        action=action,
        tg_id=int(callback.from_user.id),
    )


@router.message(_GROUP_CHAT, F.text.func(lambda t: bool(t and "#离岗报备" in t)))
async def parse_leave_sent(message: Message) -> None:
    user = _require_user(message)
    if not user:
        return
    reg, info = _user_context(tg_id=int(user.id))
    if not reg:
        log.info(
            "[LEAVE_RECORD] action=leave_skip tg_id=%s chat_id=%s reason=not_registered",
            user.id,
            message.chat.id,
        )
        return
    record_id = temporary_leave_records_repo.insert_leave(
        employee_id=str(reg.employee_id),
        english_name=str(info),
        tg_id=int(user.id),
        chat_id=int(message.chat.id),
        leave_at_utc=datetime.now(timezone.utc),
        reason=_reason_from_leave_message(message.text),
    )
    log.info(
        "[LEAVE_RECORD] action=leave id=%s tg_id=%s chat_id=%s employee_id=%s",
        record_id,
        user.id,
        message.chat.id,
        reg.employee_id,
    )


@router.message(_GROUP_CHAT, F.text.func(lambda t: bool(t and "#返岗报备" in t)))
async def parse_back_sent(message: Message) -> None:
    user = _require_user(message)
    if not user:
        return
    reg, info = _user_context(tg_id=int(user.id))
    if not reg:
        log.info(
            "[LEAVE_RECORD] action=back_skip tg_id=%s chat_id=%s reason=not_registered",
            user.id,
            message.chat.id,
        )
        return
    open_rec = temporary_leave_records_repo.get_latest_open(
        employee_id=str(reg.employee_id),
        chat_id=int(message.chat.id),
    )
    if not open_rec:
        log.info(
            "[LEAVE_RECORD] action=back_skip tg_id=%s chat_id=%s employee_id=%s reason=no_open_leave",
            user.id,
            message.chat.id,
            reg.employee_id,
        )
        return
    now_utc = datetime.now(timezone.utc)
    leave_at = open_rec.leave_at
    if isinstance(leave_at, datetime) and leave_at.tzinfo is None:
        leave_at = leave_at.replace(tzinfo=timezone.utc)
    mins = max(0, int((now_utc - leave_at).total_seconds() // 60))
    temporary_leave_records_repo.close_leave(
        record_id=int(open_rec.id),
        back_at_utc=now_utc,
        duration_minutes=mins,
        remark_required=mins > 30,
    )
    log.info(
        "[LEAVE_RECORD] action=back id=%s tg_id=%s chat_id=%s employee_id=%s mins=%s duration=%s",
        open_rec.id,
        user.id,
        message.chat.id,
        reg.employee_id,
        mins,
        _format_leave_duration_minutes(mins),
    )


async def _open_shift_web_app(*, message: Message, tg_id: int) -> None:
    if message.chat.type != "private":
        await message.reply("班表配置仅支持私聊中使用，请私聊机器人后点「班表」。")
        return
    if not admin_list_repo.is_admin_by_tg_id(tg_id=tg_id):
        await message.reply("无权限操作")
        return
    url = build_shift_web_app_url_for_admin(tg_id=tg_id)
    if not url:
        await message.reply(
            "班表 Web 未配置：请在 .env 设置 SHIFT_WEB_APP_PUBLIC_URL\n"
            "（须为 Telegram 可访问的 HTTPS 地址）"
        )
        return
    await message.reply(
        "请点下方「打开班表配置」进入编辑页：",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="打开班表配置",
                        web_app=WebAppInfo(url=url),
                    )
                ]
            ]
        ),
    )


@router.message(F.text.in_({"班表", "班次"}))
async def open_shift_web_app_message(message: Message) -> None:
    user = _require_user(message)
    if not user or message.chat.type != "private":
        return
    await _open_shift_web_app(message=message, tg_id=int(user.id))


@router.callback_query(F.data == "act:shift")
async def open_shift_web_app_callback(callback: CallbackQuery) -> None:
    """消息内 callback「班表」兜底。"""
    await callback.answer()
    if callback.message is None:
        return
    await _open_shift_web_app(
        message=callback.message,
        tg_id=int(callback.from_user.id),
    )


def _export_range_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="今日", callback_data="act:export:today"),
                InlineKeyboardButton(text="本周", callback_data="act:export:week"),
                InlineKeyboardButton(text="本月", callback_data="act:export:month"),
            ],
            [
                InlineKeyboardButton(text="昨天", callback_data="act:export:yesterday"),
                InlineKeyboardButton(text="上周", callback_data="act:export:last_week"),
                InlineKeyboardButton(text="上月", callback_data="act:export:last_month"),
            ],
        ]
    )


async def _prompt_export_range(*, message: Message, tg_id: int) -> None:
    if message.chat.type != "private":
        await message.reply("导出仅支持私聊中使用。")
        return
    if not admin_list_repo.is_admin_by_tg_id(tg_id=tg_id):
        await message.reply("无权限操作")
        return
    await message.reply("请选择导出范围：", reply_markup=_export_range_keyboard())


@router.message(F.text == "导出")
async def export_today_message(message: Message) -> None:
    user = _require_user(message)
    if not user:
        return
    await _prompt_export_range(message=message, tg_id=int(user.id))


async def _run_export(
    *,
    message: Message,
    tg_id: int,
    kind: attendance_export_service.ExportRangeKind,
) -> None:
    if message.chat.type != "private":
        await message.reply("导出仅支持私聊中使用。")
        return
    if not admin_list_repo.is_admin_by_tg_id(tg_id=tg_id):
        await message.reply("无权限操作")
        return
    cfg = load_daily_report_config()
    today = attendance_export_service.today_in_tz(tz_name=cfg.timezone_name)
    start, end, range_label = attendance_export_service.resolve_export_date_range(
        kind=kind,
        today=today,
    )
    log.info(
        "export: start tg_id=%s kind=%s range=%s..%s",
        tg_id,
        kind,
        start,
        end,
    )
    status_msg = await message.reply(
        f"正在生成{range_label}考勤导出（{start.isoformat()}～{end.isoformat()}），请稍候…"
    )
    bot = message.bot
    try:
        all_rows = await attendance_export_service.collect_rows_for_range(
            start=start,
            end=end,
            bot=bot,
        )
        pivot, overview, dates = attendance_export_service.build_pivot_and_overview(
            rows=all_rows,
            start=start,
            end=end,
        )
        body = attendance_export_service.encode_attendance_export_xlsx(
            pivot=pivot,
            dates=dates,
            overview=overview,
            range_label=range_label,
        )
        fname = attendance_export_service.export_filename(start=start, end=end)
        doc = BufferedInputFile(file=body, filename=fname)
        await message.reply_document(
            document=doc,
            caption=f"{range_label}考勤导出（{overview.expected_count} 人）",
        )
        log.info(
            "export: ok tg_id=%s kind=%s people=%s days=%s",
            tg_id,
            kind,
            overview.expected_count,
            len(dates),
        )
    except Exception:
        log.exception("export: failed tg_id=%s kind=%s", tg_id, kind)
        await message.reply("导出失败，请稍后重试或联系管理员查看服务日志。")
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass


@router.callback_query(F.data == "act:export")
async def export_today_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _prompt_export_range(message=callback.message, tg_id=int(callback.from_user.id))


_EXPORT_KIND_CALLBACKS = frozenset(
    {
        "act:export:today",
        "act:export:yesterday",
        "act:export:week",
        "act:export:last_week",
        "act:export:month",
        "act:export:last_month",
    }
)


@router.callback_query(F.data.in_(_EXPORT_KIND_CALLBACKS))
async def export_range_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    kind_map = {
        "act:export:today": "today",
        "act:export:yesterday": "yesterday",
        "act:export:week": "week",
        "act:export:last_week": "last_week",
        "act:export:month": "month",
        "act:export:last_month": "last_month",
    }
    kind = kind_map.get(str(callback.data or ""), "today")
    await _run_export(
        message=callback.message,
        tg_id=int(callback.from_user.id),
        kind=kind,  # type: ignore[arg-type]
    )


@router.callback_query(F.data == "act:switch_group")
async def switch_attendance_group_callback(callback: CallbackQuery) -> None:
    """错群时：将用户班次绑定改为当前群。"""
    await callback.answer()
    if callback.message is None or callback.message.chat.type not in ("group", "supergroup"):
        return
    res = checkin_service.switch_attendance_group_to_chat(
        tg_id=int(callback.from_user.id),
        chat_id=int(callback.message.chat.id),
    )
    await callback.message.reply(text=res.message)
