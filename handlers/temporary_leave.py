from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services import register_service
from services import temporary_leave_service

router = Router()
log = logging.getLogger(__name__)

_TLEAVE_FLOW_SKIP_USER_MSG = "流程状态异常，请重新点击【离岗报备】开始申请。"
_REGISTER_BLOCKS_MSG = "当前仍处于注册输入流程，请先完成注册，或重新点击对应功能按钮。"


class TemporaryLeavePrivateFlowExpectingTextFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if message.chat.type != "private":
            return False
        user = message.from_user
        if not user:
            return False
        if register_service.is_waiting_register_input(tg_id=user.id):
            return False
        return temporary_leave_service.is_temporary_leave_flow_expecting_text(tg_id=user.id)


@router.callback_query(F.data == "tleave:begin")
async def temporary_leave_begin_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.from_user:
        return
    user = callback.from_user
    chat = callback.message.chat
    if chat.type != "private":
        await callback.message.reply(text=temporary_leave_service.MSG_NOT_PRIVATE)
        return

    register_service.clear_waiting_register_input(tg_id=user.id)
    res = temporary_leave_service.begin_temporary_leave_application(tg_id=user.id)
    if not res.ok:
        await callback.message.reply(text=res.message)
        return

    await callback.message.reply(
        text="请以 时$分（24小时制）输入您的离岗开始时间，例如：16$25",
    )


@router.callback_query(F.data.startswith("tleave:confirm:"))
async def temporary_leave_confirm_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.from_user:
        return
    if callback.message.chat.type != "private":
        return
    token = (callback.data or "").removeprefix("tleave:confirm:")
    res = temporary_leave_service.submit_temporary_leave_application(token=token, tg_id=callback.from_user.id)
    await callback.message.reply(text=res.message)


@router.callback_query(F.data.startswith("tleave:cancel:"))
async def temporary_leave_cancel_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.from_user:
        return
    if callback.message.chat.type != "private":
        return
    token = (callback.data or "").removeprefix("tleave:cancel:")
    temporary_leave_service.cancel_temporary_leave_confirm(token=token, tg_id=callback.from_user.id)
    await callback.message.reply(text="已取消离岗报备")


@router.message(F.text, TemporaryLeavePrivateFlowExpectingTextFilter())
async def temporary_leave_flow_text_handler(message: Message) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    tid = message.from_user.id
    text = message.text or ""

    if register_service.is_waiting_register_input(tg_id=tid):
        await message.reply(text=_REGISTER_BLOCKS_MSG)
        return

    phase = temporary_leave_service.get_temporary_leave_phase(tg_id=tid)
    if phase == temporary_leave_service.STATE_WAIT_START:
        res = temporary_leave_service.consume_tleave_start_time(tg_id=tid, text=text)
        if res.error_code == "SKIP":
            await message.reply(text=_TLEAVE_FLOW_SKIP_USER_MSG)
            temporary_leave_service.clear_temporary_leave_session(tg_id=tid)
            return
        if not res.ok:
            await message.reply(text=res.message)
            return
        await message.reply(
            text="请以 时$分（24小时制）输入您的离岗结束时间，例如：17$00",
        )
        return

    if phase == temporary_leave_service.STATE_WAIT_END:
        res = temporary_leave_service.consume_tleave_end_time(tg_id=tid, text=text)
        if res.error_code == "SKIP":
            await message.reply(text=_TLEAVE_FLOW_SKIP_USER_MSG)
            temporary_leave_service.clear_temporary_leave_session(tg_id=tid)
            return
        if not res.ok:
            await message.reply(text=res.message)
            return
        await message.reply(text="请输入您的离岗原因")
        return

    if phase == temporary_leave_service.STATE_WAIT_REASON:
        res, token = temporary_leave_service.consume_tleave_reason(tg_id=tid, text=text)
        if res.error_code == "SKIP":
            await message.reply(text=_TLEAVE_FLOW_SKIP_USER_MSG)
            temporary_leave_service.clear_temporary_leave_session(tg_id=tid)
            return
        if not res.ok:
            await message.reply(text=res.message)
            return
        assert token is not None
        await message.reply(
            text=res.message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="确认", callback_data=f"tleave:confirm:{token}"),
                        InlineKeyboardButton(text="取消", callback_data=f"tleave:cancel:{token}"),
                    ],
                ]
            ),
        )
        return
