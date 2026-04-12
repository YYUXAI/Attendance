from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services import register_service
from services import rest_service
from services import temporary_leave_service


router = Router()
log = logging.getLogger(__name__)


class RegisterPrivateInputFilter(BaseFilter):
    """仅在私聊且正在等待注册输入、且不因休假文本冲突时匹配；只读判断，无副作用。"""

    async def __call__(self, message: Message) -> bool:
        if message.chat.type != "private":
            return False
        user = message.from_user
        if not user:
            return False
        tid = user.id
        if not register_service.is_waiting_register_input(tg_id=tid):
            return False
        if rest_service.is_leave_flow_expecting_text(tg_id=tid):
            return False
        if temporary_leave_service.is_temporary_leave_flow_expecting_text(tg_id=tid):
            return False
        return True


@router.callback_query(F.data == "reg:begin")
async def register_begin_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user = callback.from_user
    chat = callback.message.chat

    if chat.type != "private":
        await callback.message.reply(text="请先私聊机器人，再点击【注册】完成注册。")
        return

    rest_service.clear_leave_session(tg_id=user.id)
    temporary_leave_service.clear_temporary_leave_session(tg_id=user.id)
    register_service.mark_waiting_register_input(tg_id=user.id)
    await callback.message.reply(
        text="请输入：英文名$工号\n示例：Jeffery$72694",
    )


@router.callback_query(F.data.startswith("reg:confirm:"))
async def register_confirm_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    chat = callback.message.chat
    user = callback.from_user
    if chat.type != "private":
        return
    token = (callback.data or "").removeprefix("reg:confirm:")
    res = register_service.confirm_register(
        token=token,
        tg_id=user.id,
        registered_chat_id=chat.id,
        tg_username=user.username,
    )
    await callback.message.reply(text=res.message)


@router.callback_query(F.data.startswith("reg:cancel:"))
async def register_cancel_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    chat = callback.message.chat
    user = callback.from_user
    token = (callback.data or "").removeprefix("reg:cancel:")
    register_service.cancel_preview(token=token, tg_id=user.id)
    if chat.type == "private":
        await callback.message.reply(text="已取消")


@router.message(F.text, RegisterPrivateInputFilter())
async def register_input_message_handler(message: Message) -> None:
    tid = message.from_user.id if message.from_user else None
    text_preview = (message.text or "")[:200]
    log.info(
        "[REGISTER_HANDLER_ENTER] tg_id=%s chat_type=%s text_preview=%r",
        tid,
        message.chat.type,
        text_preview,
    )

    if message.chat.type != "private":
        log.info("[REGISTER_HANDLER_RETURN] tg_id=%s reason=not_private", tid)
        return
    if not message.from_user:
        log.info("[REGISTER_HANDLER_RETURN] tg_id=%s reason=no_from_user", tid)
        return
    if not register_service.is_waiting_register_input(tg_id=message.from_user.id):
        log.info("[REGISTER_HANDLER_RETURN] tg_id=%s reason=not_waiting_register", tid)
        return
    if rest_service.is_leave_flow_expecting_text(tg_id=message.from_user.id):
        log.info("[REGISTER_HANDLER_RETURN] tg_id=%s reason=leave_flow_expecting_yield", tid)
        return

    text = message.text or ""
    preview_or_err = register_service.preview_register(tg_id=message.from_user.id, text=text)
    if not hasattr(preview_or_err, "token"):
        await message.reply(text=preview_or_err.message)
        log.info("[REGISTER_HANDLER_RETURN] tg_id=%s reason=replied_invalid_preview", tid)
        return

    preview = preview_or_err
    await message.reply(
        text=(
            "请确认：\n\n"
            f"英文名：{preview.english_name}\n"
            f"工号：{preview.employee_id}\n"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="确认", callback_data=f"reg:confirm:{preview.token}"),
                    InlineKeyboardButton(text="取消", callback_data=f"reg:cancel:{preview.token}"),
                ],
            ]
        ),
    )
    log.info("[REGISTER_HANDLER_RETURN] tg_id=%s reason=replied_preview_ok", tid)
