from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from services import approval_service

router = Router()


class ApprovalRemarkPendingFilter(BaseFilter):
    """仅当审批人正在输入审批备注时匹配；只读，无副作用。"""

    async def __call__(self, message: Message) -> bool:
        if message.chat.type != "private":
            return False
        user = message.from_user
        if not user:
            return False
        return approval_service.has_pending_approval_remark(tg_id=user.id)


@router.callback_query(F.data.startswith("leave:apr:"))
async def leave_approval_decision_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.from_user:
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[0] != "leave" or parts[1] != "apr":
        return
    try:
        task_id = int(parts[2])
    except ValueError:
        return
    yn = (parts[3] or "").upper()
    approve = yn == "Y"
    res = approval_service.handle_approve_reject_callback(
        tg_id=callback.from_user.id,
        task_id=task_id,
        approve=approve,
    )
    await callback.message.reply(text=res.message)


@router.callback_query(F.data.startswith("apr:TEMPORARY_LEAVE:"))
async def temporary_leave_approval_decision_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.from_user:
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[0] != "apr" or parts[1] != "TEMPORARY_LEAVE":
        return
    try:
        task_id = int(parts[2])
    except ValueError:
        return
    action = (parts[3] or "").lower()
    if action == "approve":
        approve = True
    elif action == "reject":
        approve = False
    else:
        return
    res = approval_service.handle_temporary_leave_approve_reject_callback(
        tg_id=callback.from_user.id,
        task_id=task_id,
        approve=approve,
    )
    await callback.message.reply(text=res.message)


@router.message(F.text, ApprovalRemarkPendingFilter())
async def leave_approver_remark_handler(message: Message) -> None:
    if not message.from_user:
        return
    res = approval_service.handle_approver_remark_text(
        tg_id=message.from_user.id,
        text=message.text or "",
    )
    if res.error_code == "NO_DRAFT":
        return
    await message.reply(text=res.message)
