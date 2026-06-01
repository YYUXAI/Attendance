from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

log = logging.getLogger(__name__)

_START_COMMANDS = [
    BotCommand(command="start", description="打开功能菜单"),
]


async def register_bot_commands(*, bot: Bot) -> None:
    """私聊/群聊均注册 /start；私聊左侧 Menu 钮打开同一命令列表。"""
    scopes = (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
    )
    for scope in scopes:
        await bot.set_my_commands(_START_COMMANDS, scope=scope)
    # Menu 钮仅 Telegram 私聊支持；群聊请用输入框输入 /
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    log.info("bot_commands: /start in default+private+group; MenuButtonCommands for private")
