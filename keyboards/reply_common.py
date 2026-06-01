from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup

# Telegram 原生底部 ReplyKeyboard 无法设置蓝底/白字/字号，仅 Web 页内按钮可自定义样式。
DEFAULT_REPLY_KWARGS = {
    "resize_keyboard": True,
    "is_persistent": True,
    "input_field_placeholder": "选下方按钮或输入消息",
}


def build_reply_keyboard(*, rows: list[list]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=rows, **DEFAULT_REPLY_KWARGS)
