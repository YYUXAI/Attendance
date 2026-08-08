from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from infra.daily_report_config import load_daily_report_config
from infra.bot_owner import load_attendance_bot_owner
from infra.log_redaction import redacted_ref
from keyboards.actions_menu import build_shift_web_app_url_for_admin
from repositories import (
    admin_list_repo,
)
from services import attendance_export_service, checkin_service, register_service

router = Router()
log = logging.getLogger(__name__)

def _require_user(message: Message):
    return message.from_user


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
    register_service.clear_waiting_register_input(
        bot_owner=load_attendance_bot_owner(),
        tg_id=int(user.id),
    )
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
    if message.chat.type == "private":
        register_service.clear_waiting_register_input(
            bot_owner=load_attendance_bot_owner(),
            tg_id=int(user.id),
        )
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
        "export: start tg_ref=%s kind=%s range=%s..%s",
        redacted_ref(tg_id),
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
            export_tg_id=tg_id,
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
            "export: ok tg_ref=%s kind=%s people=%s days=%s",
            redacted_ref(tg_id),
            kind,
            overview.expected_count,
            len(dates),
        )
    except Exception:
        log.exception("export: failed tg_ref=%s kind=%s", redacted_ref(tg_id), kind)
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
