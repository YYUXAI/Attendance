from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from services import qc_task_lifecycle_service

router = Router(name="qc_callbacks")


def _parse_qc_callback_data(data: str) -> tuple[str, int, str] | None:
    parts = str(data).split(":")
    if len(parts) != 4 or parts[0] != "qc":
        return None
    stage, tid_s, act = parts[1], parts[2], parts[3]
    if stage not in ("f", "s") or act not in ("y", "n"):
        return None
    try:
        tid = int(tid_s)
    except (TypeError, ValueError):
        return None
    return stage, tid, act


@router.callback_query(F.data.startswith("qc:"))
async def qc_callback_handler(query: CallbackQuery) -> None:
    if query.from_user is None:
        await query.answer("无法识别操作人。", show_alert=True)
        return
    parsed = _parse_qc_callback_data(str(query.data or ""))
    if parsed is None:
        await query.answer("无效操作。", show_alert=True)
        return
    stage, task_id, act = parsed
    tg_uid = int(query.from_user.id)

    if stage == "f" and act == "y":
        ok, msg = qc_task_lifecycle_service.handle_first_confirm(task_id=task_id, tg_user_id=tg_uid)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        await query.answer()
        if query.message:
            await query.message.answer("请发布符合要求的图片")
        return

    if stage == "f" and act == "n":
        ok, msg = qc_task_lifecycle_service.handle_first_cancel(task_id=task_id, tg_user_id=tg_uid)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        await query.answer()
        if query.message:
            await query.message.answer("已记录为本轮质检失败。")
        return

    if stage == "s" and act == "n":
        ok, msg = qc_task_lifecycle_service.handle_second_cancel(task_id=task_id, tg_user_id=tg_uid)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        await query.answer()
        if query.message:
            await query.message.answer("已取消本次提交，请重新上传截图。")
        return

    if stage == "s" and act == "y":
        ok, msg = qc_task_lifecycle_service.handle_second_confirm(task_id=task_id, tg_user_id=tg_uid)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        await query.answer()
        if query.message:
            await query.message.answer("您的本轮质检已经完成，谢谢您的配合。")
        return

    await query.answer("未知操作。", show_alert=True)
