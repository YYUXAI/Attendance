from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_CONFIRM = "aex1:ok"
CALLBACK_CANCEL = "aex1:cancel"


def build_admin_export_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="确认", callback_data=CALLBACK_CONFIRM),
                InlineKeyboardButton(text="取消", callback_data=CALLBACK_CANCEL),
            ]
        ]
    )
