from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from keyboards.main_menu import PRIVATE_REPLY_MENU_TEXTS
from infra.bot_owner import load_attendance_bot_owner
from infra.log_redaction import redacted_ref, text_summary
from repositories import registrations_repo
from services import register_service


router = Router()
log = logging.getLogger(__name__)

_ATTENDANCE_REGISTER_COMMAND_RE = re.compile(r"^/attendance_register(?:@\w+)?(?:\s|$)")


class RegisterPrivateInputFilter(BaseFilter):
    """仅在私聊且正在等待注册输入时匹配；只读判断，无副作用。"""

    async def __call__(self, message: Message) -> bool:
        if message.chat.type != "private":
            return False
        user = message.from_user
        if not user:
            return False
        tid = user.id
        if not register_service.is_waiting_register_input(
            bot_owner=load_attendance_bot_owner(),
            tg_id=tid,
            private_chat_id=int(message.chat.id),
        ):
            return False
        text = (message.text or "").strip()
        if text in PRIVATE_REPLY_MENU_TEXTS:
            return False
        return True


class RegisterBeginInputFilter(BaseFilter):
    """私聊注册入口：兼容中文按钮文案和统一壳菜单命令。"""

    async def __call__(self, message: Message) -> bool:
        if message.chat.type != "private":
            return False
        text = (message.text or "").strip()
        return text in {"注册", "绑定考勤资料"} or bool(_ATTENDANCE_REGISTER_COMMAND_RE.match(text))


async def _begin_register_in_private(*, message: Message, tg_id: int) -> None:
    bot_owner = load_attendance_bot_owner()
    if registrations_repo.get_by_tg_id(int(tg_id)) is not None:
        register_service.clear_waiting_register_input(bot_owner=bot_owner, tg_id=tg_id)
        await message.reply(text="您已经注册过了")
        return
    register_service.mark_waiting_register_input(
        bot_owner=bot_owner,
        tg_id=tg_id,
        private_chat_id=int(message.chat.id),
    )
    await message.reply(
        text=(
            "请私聊发送一行（不要复制「请输入」「示例」等提示）：\n"
            "英文名$工号\n"
            "例如：GRANDFOR$74808"
        )
    )


@router.message(F.text, RegisterBeginInputFilter())
async def register_begin_message(message: Message) -> None:
    user = message.from_user
    if not user or message.chat.type != "private":
        return
    await _begin_register_in_private(message=message, tg_id=int(user.id))


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

    await _begin_register_in_private(message=callback.message, tg_id=int(user.id))


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
        bot_owner=load_attendance_bot_owner(),
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
    res = register_service.cancel_preview(
        bot_owner=load_attendance_bot_owner(),
        token=token,
        tg_id=user.id,
        private_chat_id=chat.id,
    )
    if chat.type == "private":
        await callback.message.reply(text=res.message)


@router.message(F.text, RegisterPrivateInputFilter())
async def register_input_message_handler(message: Message) -> None:
    tid = message.from_user.id if message.from_user else None
    log.info(
        "[REGISTER_HANDLER_ENTER] tg_ref=%s chat_type=%s text=%s",
        redacted_ref(tid),
        message.chat.type,
        text_summary(message.text),
    )

    if message.chat.type != "private":
        log.info("[REGISTER_HANDLER_RETURN] tg_ref=%s reason=not_private", redacted_ref(tid))
        return
    if not message.from_user:
        log.info("[REGISTER_HANDLER_RETURN] tg_ref=%s reason=no_from_user", redacted_ref(tid))
        return
    bot_owner = load_attendance_bot_owner()
    if not register_service.is_waiting_register_input(
        bot_owner=bot_owner,
        tg_id=message.from_user.id,
        private_chat_id=int(message.chat.id),
    ):
        log.info("[REGISTER_HANDLER_RETURN] tg_ref=%s reason=not_waiting_register", redacted_ref(tid))
        return
    text = message.text or ""
    preview_or_err = register_service.preview_register(
        bot_owner=bot_owner,
        tg_id=message.from_user.id,
        private_chat_id=message.chat.id,
        text=text,
    )
    if not hasattr(preview_or_err, "token"):
        await message.reply(text=preview_or_err.message)
        log.info("[REGISTER_HANDLER_RETURN] tg_ref=%s reason=replied_invalid_preview", redacted_ref(tid))
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
    log.info("[REGISTER_HANDLER_RETURN] tg_ref=%s reason=replied_preview_ok", redacted_ref(tid))
