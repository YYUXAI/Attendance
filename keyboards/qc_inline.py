from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_first_stage_keyboard(*, task_id: int) -> InlineKeyboardMarkup:
    tid = int(task_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="确认", callback_data=f"qc:f:{tid}:y"),
                InlineKeyboardButton(text="取消", callback_data=f"qc:f:{tid}:n"),
            ],
        ]
    )


def build_second_stage_keyboard(*, task_id: int) -> InlineKeyboardMarkup:
    tid = int(task_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="确认", callback_data=f"qc:s:{tid}:y"),
                InlineKeyboardButton(text="取消", callback_data=f"qc:s:{tid}:n"),
            ],
        ]
    )
