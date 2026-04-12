from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="注册", callback_data="reg:begin"),
                InlineKeyboardButton(text="我的信息", callback_data="profile:myinfo"),
            ],
            [
                InlineKeyboardButton(text="报备休息", callback_data="noop:rest"),
                InlineKeyboardButton(text="离岗报备", callback_data="tleave:begin"),
            ],
        ]
    )
