from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from keyboards.leave_types import build_leave_type_keyboard
from services import approval_service
from services import register_service
from services import rest_service
from services import temporary_leave_service

router = Router()
log = logging.getLogger(__name__)

_LEAVE_FLOW_SKIP_USER_MSG = "流程状态异常，请重新点击【报备休息】开始申请。"
_REGISTER_BLOCKS_LEAVE_MSG = "当前仍处于注册输入流程，请先完成注册，或重新点击对应功能按钮。"


class LeavePrivateFlowExpectingTextFilter(BaseFilter):
    """仅私聊、有发送者、且休假流程正在等待文本时匹配；只读判断，无副作用。"""

    async def __call__(self, message: Message) -> bool:
        if message.chat.type != "private":
            return False
        user = message.from_user
        if not user:
            return False
        if temporary_leave_service.is_temporary_leave_flow_expecting_text(tg_id=user.id):
            return False
        return rest_service.is_leave_flow_expecting_text(tg_id=user.id)


async def _reply_leave_skip_and_clear(message: Message, tg_id: int) -> None:
    rest_service.clear_leave_session(tg_id=tg_id)
    await message.reply(text=_LEAVE_FLOW_SKIP_USER_MSG)


@router.callback_query(F.data == "noop:rest")
async def leave_begin_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user = callback.from_user
    chat = callback.message.chat
    if chat.type != "private":
        await callback.message.reply(text="请先私信机器人，再点击【报备休息】提交休假申请。")
        return

    register_service.clear_waiting_register_input(tg_id=user.id)

    res = rest_service.begin_leave_application(tg_id=user.id)
    if not res.ok:
        await callback.message.reply(text=res.message)
        return

    await callback.message.reply(
        text="请选择您要申请的休假类型：",
        reply_markup=build_leave_type_keyboard(),
    )


@router.callback_query(F.data.startswith("leave:type:"))
async def leave_type_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user = callback.from_user
    if callback.message.chat.type != "private":
        return

    key = (callback.data or "").removeprefix("leave:type:")
    res = rest_service.on_leave_type_chosen(tg_id=user.id, type_key=key)
    if not res.ok:
        await callback.message.reply(text=res.message)
        return

    if key == "other":
        await callback.message.reply(text="请输入您的休假类型")
        return

    await callback.message.reply(
        text="请输入您申请的休假开始日期，按 年$月$日 的格式输入，例如：\n2026$4$3",
    )


@router.callback_query(F.data.startswith("leave:confirm:"))
async def leave_confirm_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user = callback.from_user
    if callback.message.chat.type != "private":
        return
    token = (callback.data or "").removeprefix("leave:confirm:")
    res = rest_service.submit_leave_application(token=token, tg_id=user.id)
    await callback.message.reply(text=res.message)
    if res.ok and res.leave_application_id is not None:
        await approval_service.try_dispatch_after_leave_submit(
            bot=callback.bot,
            leave_application_id=res.leave_application_id,
        )


@router.callback_query(F.data.startswith("leave:cancel:"))
async def leave_cancel_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user = callback.from_user
    if callback.message.chat.type != "private":
        return
    token = (callback.data or "").removeprefix("leave:cancel:")
    rest_service.cancel_leave_confirm(token=token, tg_id=user.id)
    await callback.message.reply(text="已取消")


@router.message(F.text, LeavePrivateFlowExpectingTextFilter())
async def leave_flow_text_handler(message: Message) -> None:
    tid = message.from_user.id if message.from_user else None
    text_for_log = (message.text or "")[:200]
    phase_pre = rest_service.get_leave_phase(tg_id=tid) if tid is not None else None
    reg_wait_pre = register_service.is_waiting_register_input(tg_id=tid) if tid is not None else False
    leave_exp_pre = rest_service.is_leave_flow_expecting_text(tg_id=tid) if tid is not None else False
    log.info(
        "[REST_HANDLER_ENTER] tg_id=%s chat_type=%s phase=%s register_waiting=%s leave_expecting=%s text_preview=%r",
        tid,
        message.chat.type,
        phase_pre,
        reg_wait_pre,
        leave_exp_pre,
        text_for_log,
    )

    if message.chat.type != "private":
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=not_private", tid)
        return
    if not message.from_user:
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=no_from_user", tid)
        return

    tid = message.from_user.id
    text = message.text or ""
    text_for_log = text if len(text) <= 200 else text[:200] + "…"
    phase = rest_service.get_leave_phase(tg_id=tid)
    register_waiting = register_service.is_waiting_register_input(tg_id=tid)
    leave_expecting = rest_service.is_leave_flow_expecting_text(tg_id=tid)
    log.info(
        "[REST_HANDLER_STATE] tg_id=%s phase=%s register_waiting=%s leave_expecting=%s text_preview=%r",
        tid,
        phase,
        register_waiting,
        leave_expecting,
        text_for_log,
    )

    if register_waiting:
        if leave_expecting:
            await message.reply(text=_REGISTER_BLOCKS_LEAVE_MSG)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=register_waiting_replied_leave_conflict", tid)
            return
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=register_waiting", tid)
        return
    if not leave_expecting:
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=not_leave_expecting", tid)
        return

    if phase == rest_service.STATE_WAIT_CUSTOM:
        res = rest_service.consume_custom_leave_type(tg_id=tid, text=text)
        if res.error_code == "SKIP":
            await _reply_leave_skip_and_clear(message, tid)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=skip_from_consume_custom", tid)
            return
        if not res.ok:
            await message.reply(text=res.message)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_consume_custom_error", tid)
            return
        await message.reply(
            text="请输入您申请的休假开始日期，按 年$月$日 的格式输入，例如：\n2026$4$3",
        )
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_prompt_start_date", tid)
        return

    if phase == rest_service.STATE_WAIT_START:
        res = rest_service.consume_start_date(tg_id=tid, text=text)
        if res.error_code == "SKIP":
            await _reply_leave_skip_and_clear(message, tid)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=skip_from_consume_start_date", tid)
            return
        if not res.ok:
            await message.reply(text=res.message)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_consume_start_date_error", tid)
            return
        await message.reply(
            text="请输入您申请的休假结束日期，按 年$月$日 的格式输入，例如：\n2026$4$3",
        )
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_prompt_end_date", tid)
        return

    if phase == rest_service.STATE_WAIT_END:
        res = rest_service.consume_end_date(tg_id=tid, text=text)
        if res.error_code == "SKIP":
            await _reply_leave_skip_and_clear(message, tid)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=skip_from_consume_end_date", tid)
            return
        if not res.ok:
            await message.reply(text=res.message)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_consume_end_date_error", tid)
            return
        await message.reply(
            text="请输入您申请休假的备注信息。输入 /null 可跳过此步骤。",
        )
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_prompt_remark", tid)
        return

    if phase == rest_service.STATE_WAIT_REMARK:
        res, token = rest_service.consume_remark(tg_id=tid, text=text)
        if res.error_code == "SKIP":
            await _reply_leave_skip_and_clear(message, tid)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=skip_from_consume_remark", tid)
            return
        if not res.ok:
            await message.reply(text=res.message)
            log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_consume_remark_error", tid)
            return
        assert token is not None
        await message.reply(
            text=res.message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="确认", callback_data=f"leave:confirm:{token}"),
                        InlineKeyboardButton(text="取消", callback_data=f"leave:cancel:{token}"),
                    ],
                ]
            ),
        )
        log.info("[REST_HANDLER_RETURN] tg_id=%s reason=replied_confirm_keyboard", tid)
        return

    log.info("[REST_HANDLER_RETURN] tg_id=%s reason=unexpected_phase_after_gate phase=%s", tid, phase)
