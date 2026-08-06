from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, WebAppInfo

from keyboards.reply_common import build_reply_keyboard

# 私聊底部 ReplyKeyboard 文案；注册等待输入时需放行，交给对应 handler 处理
PRIVATE_REPLY_MENU_TEXTS = frozenset({"注册", "个人", "导出", "班表", "我的信息", "班次"})

# 群聊底部按钮：点击后等同 /start，在对话内用 Inline 选择具体操作
GROUP_REPLY_MENU_TEXTS = frozenset({"签到", "签退", "离岗", "返岗"})


def build_private_actions_inline(
    *,
    is_admin: bool,
    shift_web_app_url: str | None = None,
) -> InlineKeyboardMarkup:
    """私聊：注册/个人；管理员另有导出/班表（班表一点即开 Web App）。"""
    rows = [
        [
            InlineKeyboardButton(text="注册", callback_data="reg:begin"),
            InlineKeyboardButton(text="个人", callback_data="profile:myinfo"),
        ],
    ]
    if is_admin:
        shift_btn = (
            InlineKeyboardButton(text="班表", web_app=WebAppInfo(url=shift_web_app_url))
            if shift_web_app_url
            else InlineKeyboardButton(text="班表", callback_data="act:shift")
        )
        rows.append(
            [
                InlineKeyboardButton(text="导出", callback_data="act:export"),
                shift_btn,
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_private_reply_keyboard(
    *,
    is_admin: bool,
    shift_web_app_url: str | None = None,
):
    """私聊底部常驻：注册/个人；管理员另有导出/班表（班表可一点开 Web App）。"""
    rows = [
        [
            KeyboardButton(text="注册"),
            KeyboardButton(text="个人"),
        ],
    ]
    if is_admin:
        if shift_web_app_url:
            shift_btn = KeyboardButton(
                text="班表",
                web_app=WebAppInfo(url=shift_web_app_url),
            )
        else:
            shift_btn = KeyboardButton(text="班表")
        rows.append(
            [
                KeyboardButton(text="导出"),
                shift_btn,
            ]
        )
    return build_reply_keyboard(rows=rows)


def build_group_reply_keyboard():
    """群聊底部常驻：签到/签退/离岗/返岗（点击后打开功能菜单）。"""
    rows = [
        [
            KeyboardButton(text="签到"),
            KeyboardButton(text="签退"),
        ],
        [
            KeyboardButton(text="离岗"),
            KeyboardButton(text="返岗"),
        ],
    ]
    return build_reply_keyboard(rows=rows)
