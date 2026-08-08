from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, User

from keyboards.actions_menu import reply_actions_menu
from repositories.admin_list_repo import is_admin_by_tg_id

router = Router()
log = logging.getLogger(__name__)


async def _send_actions_menu(message: Message, *, user: User | None = None) -> None:
    user = user or message.from_user
    is_admin = is_admin_by_tg_id(tg_id=int(user.id)) if user else False
    await reply_actions_menu(
        message=message,
        is_admin=is_admin,
        tg_id=int(user.id) if user else None,
    )


@router.message(CommandStart())
async def start_command_handler(message: Message) -> None:
    await _send_actions_menu(message)


@router.message(Command("attendance"), F.chat.type == "private")
async def attendance_menu_command(message: Message) -> None:
    await _send_actions_menu(message)


@router.callback_query(F.data == "menu:show")
async def show_menu_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _send_actions_menu(callback.message, user=callback.from_user)


@router.callback_query(F.data == "uxa:attendance_menu")
async def unified_attendance_menu_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _send_actions_menu(callback.message, user=callback.from_user)


async def _disabled_legacy_callback(callback: CallbackQuery, *, tag: str) -> None:
    """已下线功能旧按钮：保持原 Attendance 静默处理契约。"""
    await callback.answer()
    tg_id = callback.from_user.id if callback.from_user else None
    log.info("disabled_feature callback=%s tg_id=%s data=%r", tag, tg_id, callback.data)


@router.callback_query(F.data == "noop:rest")
async def disabled_rest_begin_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="noop:rest")


@router.callback_query(F.data.startswith("leave:type:"))
async def disabled_rest_type_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="leave:type")


@router.callback_query(F.data.startswith("leave:confirm:"))
async def disabled_rest_confirm_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="leave:confirm")


@router.callback_query(F.data.startswith("leave:cancel:"))
async def disabled_rest_cancel_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="leave:cancel")


@router.callback_query(F.data.startswith("leave:apr:"))
async def disabled_rest_approval_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="leave:apr")


@router.callback_query(F.data == "tleave:begin")
async def disabled_tleave_begin_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="tleave:begin")


@router.callback_query(F.data.startswith("tleave:confirm:"))
async def disabled_tleave_confirm_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="tleave:confirm")


@router.callback_query(F.data.startswith("tleave:cancel:"))
async def disabled_tleave_cancel_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="tleave:cancel")


@router.callback_query(F.data.startswith("apr:TEMPORARY_LEAVE:"))
async def disabled_tleave_approval_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="apr:TEMPORARY_LEAVE")


@router.callback_query(F.data.startswith("qc:"))
async def disabled_qc_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="qc")


@router.callback_query(F.data.startswith("qcv:"))
async def disabled_qcv_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="qcv")
