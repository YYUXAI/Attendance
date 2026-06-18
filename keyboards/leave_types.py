from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_leave_type_keyboard() -> InlineKeyboardMarkup:
    """六类休假：callback 使用短英文枚举，避免 callback_data 过长。"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="周休", callback_data="leave:type:weekly"),
                InlineKeyboardButton(text="签证假", callback_data="leave:type:visa"),
            ],
            [
                InlineKeyboardButton(text="年假", callback_data="leave:type:annual"),
                InlineKeyboardButton(text="事假", callback_data="leave:type:personal"),
            ],
            [
                InlineKeyboardButton(text="病假", callback_data="leave:type:sick"),
                InlineKeyboardButton(text="其他", callback_data="leave:type:other"),
            ],
        ]
    )
