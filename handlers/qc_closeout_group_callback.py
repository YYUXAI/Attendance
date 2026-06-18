from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery

from repositories import qc_results_repo, shifts_repo

log = logging.getLogger(__name__)

router = Router(name="qc_closeout_group_callbacks")

_QC_VIEW_PIC_FAIL = "该截图暂不可查看"


def _parse_qcv_pic_callback(data: str) -> int | None:
    parts = str(data or "").split(":")
    if len(parts) != 3 or parts[0] != "qcv" or parts[1] != "pic":
        return None
    try:
        return int(parts[2])
    except (TypeError, ValueError):
        return None


@router.callback_query(F.data.startswith("qcv:"))
async def qc_closeout_view_screenshot_cb(query: CallbackQuery, bot: Bot) -> None:
    rid = _parse_qcv_pic_callback(str(query.data or ""))
    if rid is None or rid <= 0:
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return
    if query.message is None or query.message.chat is None:
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return

    chat_id = int(query.message.chat.id)
    row = qc_results_repo.get_by_id(result_id=int(rid))
    if row is None:
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return
    if row.result != "PASS":
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return
    att = (row.attachment_id or "").strip()
    if not att:
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return

    shift = shifts_repo.get_by_id(int(row.shift_id))
    if shift is None or shift.attendance_group_id is None or int(shift.attendance_group_id) == 0:
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return
    if chat_id != int(shift.attendance_group_id):
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return

    try:
        try:
            await bot.send_document(
                chat_id=chat_id,
                document=att,
                reply_to_message_id=int(query.message.message_id),
            )
        except TelegramBadRequest:
            await bot.send_photo(
                chat_id=chat_id,
                photo=att,
                reply_to_message_id=int(query.message.message_id),
            )
    except TelegramForbiddenError as e:
        log.warning(
            "qc_closeout_view_screenshot forbidden result_id=%s chat_id=%s err=%s",
            int(rid),
            chat_id,
            e,
        )
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return
    except TelegramBadRequest as e:
        log.warning(
            "qc_closeout_view_screenshot bad_request result_id=%s chat_id=%s err=%s",
            int(rid),
            chat_id,
            e,
        )
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return
    except Exception as e:
        log.exception(
            "qc_closeout_view_screenshot failed result_id=%s chat_id=%s exc_type=%s",
            int(rid),
            chat_id,
            type(e).__name__,
        )
        await query.answer(_QC_VIEW_PIC_FAIL, show_alert=True)
        return

    await query.answer()
