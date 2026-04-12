from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

log = logging.getLogger(__name__)


async def send_qc_private_placeholder(*, bot: Bot, tg_id: int, text: str) -> bool:
    """
    质检首条私信占位发送（非 notification_queue）。
    成功返回 True；失败记录日志并返回 False（不写 first_private_notify_sent_at）。
    """
    try:
        await bot.send_message(
            chat_id=int(tg_id),
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except TelegramForbiddenError as e:
        log.warning("qc_dm forbidden tg_id=%s exc=%r", tg_id, e)
        return False
    except TelegramBadRequest as e:
        log.warning("qc_dm bad_request tg_id=%s exc=%r", tg_id, e)
        return False
    except Exception as e:
        log.warning("qc_dm failed tg_id=%s exc=%r", tg_id, e)
        return False


async def send_qc_private_open(
    *,
    bot: Bot,
    tg_id: int,
    caption_html: str,
    example_file_id: Optional[str],
    reply_markup: InlineKeyboardMarkup,
) -> bool:
    """
    首条质检私信：可选携带班次示例 file_id；必须带首轮操作按钮。
    示例 file_id 可能对应图片或文件：先 send_document，遇 TelegramBadRequest 再尝试 send_photo。
    """
    parse_mode = "HTML"
    cid = int(tg_id)
    fid = str(example_file_id).strip() if example_file_id else ""
    try:
        if fid:
            try:
                await bot.send_document(
                    chat_id=cid,
                    document=fid,
                    caption=caption_html,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            except TelegramBadRequest:
                await bot.send_photo(
                    chat_id=cid,
                    photo=fid,
                    caption=caption_html,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
        else:
            await bot.send_message(
                chat_id=cid,
                text=caption_html,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        return True
    except TelegramForbiddenError as e:
        log.warning("qc_dm open forbidden tg_id=%s exc=%r", tg_id, e)
        return False
    except TelegramBadRequest as e:
        log.warning("qc_dm open bad_request tg_id=%s exc=%r", tg_id, e)
        return False
    except Exception as e:
        log.warning("qc_dm open failed tg_id=%s exc=%r", tg_id, e)
        return False


async def send_qc_echo_submission(
    *,
    bot: Bot,
    chat_id: int,
    file_id: str,
    caption_html: str,
    reply_markup: InlineKeyboardMarkup,
    is_photo: bool,
) -> bool:
    """回显用户上传的 file_id，并附带二次确认按钮。"""
    try:
        cid = int(chat_id)
        fid = str(file_id)
        if is_photo:
            await bot.send_photo(
                chat_id=cid,
                photo=fid,
                caption=caption_html,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        else:
            await bot.send_document(
                chat_id=cid,
                document=fid,
                caption=caption_html,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return True
    except TelegramBadRequest as e:
        log.warning("qc_dm echo bad_request chat_id=%s exc=%r", chat_id, e)
        return False
    except Exception as e:
        log.warning("qc_dm echo failed chat_id=%s exc=%r", chat_id, e)
        return False
