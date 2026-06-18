from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message

from infra.qc_dm import send_qc_echo_submission
from keyboards.qc_inline import build_second_stage_keyboard
from services import qc_task_lifecycle_service

router = Router(name="qc_messages")


def _extract_file_id_and_kind(message: Message) -> tuple[str, bool] | None:
    if message.photo:
        return str(message.photo[-1].file_id), True
    if message.document and message.document.file_id:
        return str(message.document.file_id), False
    return None


@router.message(F.chat.type == "private", F.photo | F.document)
async def qc_attachment_private_handler(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    ext = _extract_file_id_and_kind(message)
    if ext is None:
        return
    file_id, is_photo = ext
    out = qc_task_lifecycle_service.handle_attachment_upload_for_tg_user(
        tg_user_id=int(message.from_user.id),
        file_id=file_id,
    )
    if not out.ok:
        await message.answer(out.message)
        return
    if out.echo_file_id is None or out.task_id is None:
        await message.answer("处理失败，请稍后重试。")
        return
    cap = (
        "请检查您的截图是否正确，如果无误请点击【确认】，结果将发送至质检人员处。"
        "如果需要修改请点击【取消】。"
    )
    ok = await send_qc_echo_submission(
        bot=bot,
        chat_id=int(message.chat.id),
        file_id=out.echo_file_id,
        caption_html=cap,
        reply_markup=build_second_stage_keyboard(task_id=int(out.task_id)),
        is_photo=is_photo,
    )
    if not ok:
        await message.answer("回显材料失败，请稍后重试或联系管理员。")
