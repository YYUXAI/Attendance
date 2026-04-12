from __future__ import annotations

"""
Telegram 实际发送层（仅用于 notification_queue worker）。

强约束（docs05）：
- 只发送 reply_content
- 不允许根据 template_id 拼装文案
- handler 内交互消息不属于通知模块范围，仍由 handlers 直接 reply
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup


@dataclass(frozen=True)
class SendOutcome:
    delivery_result: str  # SENT / FAILED / UNDELIVERABLE
    error_message: str | None = None


async def send_notification(
    *,
    bot: Bot,
    notify_tg_id: int,
    reply_content: str,
    attachment_id: Optional[str],
    reply_markup: Optional["InlineKeyboardMarkup"] = None,
) -> SendOutcome:
    """
    返回 delivery_result 分类：
    - SENT：成功发送
    - FAILED：临时失败（可重试）
    - UNDELIVERABLE：不可送达（终态，不可重试）
    """
    try:
        # 约束收口：notification_queue 发出的消息统一按 HTML 解析。
        # 纯文本在 HTML parse_mode 下也能正常显示；如需展示字面量的 <、& 等，
        # 应在“生成 reply_content 的模板层”进行 html.escape，而不是在发送层二次处理。
        parse_mode = "HTML"
        if attachment_id:
            await bot.send_document(
                chat_id=notify_tg_id,
                document=attachment_id,
                caption=reply_content,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        else:
            await bot.send_message(
                chat_id=notify_tg_id,
                text=reply_content,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        return SendOutcome(delivery_result="SENT", error_message=None)
    except TelegramForbiddenError as e:
        # 典型：用户未与 bot 建立会话 / bot 被拉黑 / 无权限等
        return SendOutcome(delivery_result="UNDELIVERABLE", error_message=str(e))
    except TelegramBadRequest as e:
        # 典型：chat 不存在 / chat_id 无效等
        return SendOutcome(delivery_result="UNDELIVERABLE", error_message=str(e))
    except Exception as e:
        return SendOutcome(delivery_result="FAILED", error_message=str(e))
