from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from keyboards.actions_menu import reply_actions_menu, reply_group_single_fill_menu
from keyboards.main_menu import GROUP_REPLY_MENU_TEXTS

_GROUP_BOTTOM_ACTION = {
    "签到": "signin",
    "签退": "signout",
    "离岗": "leave",
    "返岗": "back",
}
from repositories.admin_list_repo import is_admin_by_tg_id

router = Router()
log = logging.getLogger(__name__)

async def _send_actions_menu(message: Message) -> None:
    user = message.from_user
    is_admin = is_admin_by_tg_id(tg_id=int(user.id)) if user else False
    await reply_actions_menu(
        message=message,
        is_admin=is_admin,
        tg_id=int(user.id) if user else None,
    )


@router.message(CommandStart())
async def start_command_handler(message: Message) -> None:
    await _send_actions_menu(message)


@router.message(
    F.text.in_(set(GROUP_REPLY_MENU_TEXTS)),
    F.chat.type.in_({"group", "supergroup"}),
)
async def group_bottom_menu_trigger(message: Message) -> None:
    """群聊底部按钮：只弹与所点项相同的一个 ↗ 按钮。"""
    user = message.from_user
    if not user:
        return
    action = _GROUP_BOTTOM_ACTION.get((message.text or "").strip())
    if not action:
        await _send_actions_menu(message)
        return
    await reply_group_single_fill_menu(
        message=message,
        action=action,
        tg_id=int(user.id),
    )


@router.callback_query(F.data == "menu:show")
async def show_menu_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user = callback.from_user
    is_admin = is_admin_by_tg_id(tg_id=int(user.id))
    await reply_actions_menu(message=callback.message, is_admin=is_admin, tg_id=int(user.id))


async def _disabled_legacy_callback(callback: CallbackQuery, *, tag: str) -> None:
    """已下线功能（报备休息/私聊离岗审批/审批/QC）旧按钮：静默忽略，仅记日志。"""
    await callback.answer()
    tg_id = callback.from_user.id if callback.from_user else None
    log.info("disabled_feature callback=%s tg_id=%s data=%r", tag, tg_id, callback.data)


# --- 报备休息（请假）---
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


# --- 私聊离岗报备 + 审批 ---
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


# --- 质检（QC）---
@router.callback_query(F.data.startswith("qc:"))
async def disabled_qc_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="qc")


@router.callback_query(F.data.startswith("qcv:"))
async def disabled_qcv_callback(callback: CallbackQuery) -> None:
    await _disabled_legacy_callback(callback, tag="qcv")
