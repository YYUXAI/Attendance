from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

from infra.gateway_group_scope import attendance_group_chat_ids

log = logging.getLogger(__name__)

_START_COMMANDS = [
    BotCommand(command="start", description="打开功能菜单"),
]

# 群隐私开启时，底部 Reply 键盘须发 / 命令 Bot 才能收到
_GROUP_ACTION_COMMANDS = [
    BotCommand(command="start", description="打开功能菜单"),
    BotCommand(command="signin", description="签到（弹出 ↗ 模板）"),
    BotCommand(command="signout", description="签退（弹出 ↗ 模板）"),
    BotCommand(command="leave", description="离岗报备"),
    BotCommand(command="back", description="返岗报备"),
]


async def register_bot_commands(*, bot: Bot) -> None:
    """私聊/群聊均注册 /start；考勤群单独注册 signin 等；Omni 群不出现考勤命令。"""
    for scope in (BotCommandScopeDefault(), BotCommandScopeAllPrivateChats()):
        await bot.set_my_commands(_START_COMMANDS, scope=scope)
    await bot.set_my_commands(_START_COMMANDS, scope=BotCommandScopeAllGroupChats())
    for chat_id in attendance_group_chat_ids():
        try:
            await bot.set_my_commands(
                _GROUP_ACTION_COMMANDS,
                scope=BotCommandScopeChat(chat_id=int(chat_id)),
            )
        except Exception as e:
            log.warning("bot_commands: attendance chat_id=%s register failed: %s", chat_id, e)
    # Menu 钮仅 Telegram 私聊支持；群聊请用输入框输入 /
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    log.info("bot_commands: /start in default+private+group; MenuButtonCommands for private")
