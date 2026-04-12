from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from keyboards.main_menu import build_main_menu_keyboard


router = Router()


@router.message(CommandStart())
async def start_command_handler(message: Message) -> None:
    await message.reply(text="请选择功能：", reply_markup=build_main_menu_keyboard())


