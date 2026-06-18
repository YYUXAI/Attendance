from __future__ import annotations

import logging
from datetime import date
from aiogram import F, Router
from aiogram.filters import BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from keyboards.admin_export import (
    CALLBACK_CANCEL,
    CALLBACK_CONFIRM,
    build_admin_export_confirm_keyboard,
)
from services import admin_export_test_service as ex
from states.admin_export_states import AdminExportTestStates

router = Router()
log = logging.getLogger(__name__)


def _is_standard_test_1_command_line(s: str) -> bool:
    t = s.strip()
    if t == "/test_1":
        return True
    if t.startswith("/test_1@") and " " not in t and len(t) > len("/test_1@"):
        return True
    return False


class AdminTest1CommandFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if message.text is not None and _is_standard_test_1_command_line(message.text):
            return True
        if message.caption is not None and _is_standard_test_1_command_line(message.caption):
            return True
        return False


class NonPrivateChatFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.chat.type != "private"


@router.message(AdminTest1CommandFilter(), NonPrivateChatFilter())
async def admin_export_test_1_non_private(message: Message) -> None:
    await message.reply(text=ex.MSG_NON_PRIVATE)


@router.message(AdminTest1CommandFilter(), F.chat.type == "private")
async def admin_export_test_1_entry(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return
    allowed, err = ex.check_admin_for_export(tg_id=int(user.id))
    if not allowed:
        await message.reply(text=err or ex.MSG_NO_PERMISSION)
        return
    await state.clear()
    await state.set_state(AdminExportTestStates.waiting_shift_id)
    await message.reply(text=ex.MSG_PROMPT_SHIFT_ID)


@router.message(
    StateFilter(AdminExportTestStates.waiting_shift_id),
    F.chat.type == "private",
    F.text,
)
async def admin_export_shift_id_step(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return
    allowed, err = ex.check_admin_for_export(tg_id=int(user.id))
    if not allowed:
        await state.clear()
        await message.reply(text=err or ex.MSG_NO_PERMISSION)
        return
    sid, perr = ex.parse_shift_id_input(text=message.text or "")
    if perr:
        await message.reply(text=perr)
        return
    await state.update_data(export_shift_id=int(sid))
    await state.set_state(AdminExportTestStates.waiting_start_date)
    await message.reply(text=ex.MSG_PROMPT_START_DATE)


@router.message(
    StateFilter(AdminExportTestStates.waiting_start_date),
    F.chat.type == "private",
    F.text,
)
async def admin_export_start_date_step(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return
    allowed, err = ex.check_admin_for_export(tg_id=int(user.id))
    if not allowed:
        await state.clear()
        await message.reply(text=err or ex.MSG_NO_PERMISSION)
        return
    d, perr = ex.parse_ymd_dollar(text=message.text or "")
    if perr:
        await message.reply(text=perr)
        return
    await state.update_data(export_start_date_iso=d.isoformat())
    await state.set_state(AdminExportTestStates.waiting_end_date)
    await message.reply(text=ex.MSG_PROMPT_END_DATE)


@router.message(
    StateFilter(AdminExportTestStates.waiting_end_date),
    F.chat.type == "private",
    F.text,
)
async def admin_export_end_date_step(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return
    allowed, err = ex.check_admin_for_export(tg_id=int(user.id))
    if not allowed:
        await state.clear()
        await message.reply(text=err or ex.MSG_NO_PERMISSION)
        return
    end_d, perr = ex.parse_ymd_dollar(text=message.text or "")
    if perr:
        await message.reply(text=perr)
        return
    data = await state.get_data()
    start_raw = data.get("export_start_date_iso")
    start_d = date.fromisoformat(start_raw) if isinstance(start_raw, str) else None
    if start_d is None:
        await state.clear()
        await message.reply(text=ex.MSG_EXPORT_FAILED)
        return
    if end_d < start_d:
        await message.reply(text=ex.MSG_END_BEFORE_START)
        return
    sid = data.get("export_shift_id")
    if not isinstance(sid, int):
        await state.clear()
        await message.reply(text=ex.MSG_EXPORT_FAILED)
        return
    await state.update_data(export_end_date_iso=end_d.isoformat())
    await state.set_state(AdminExportTestStates.waiting_confirm)
    body = ex.format_confirm_message(shift_id=int(sid), start_date=start_d, end_date=end_d)
    await message.reply(text=body, reply_markup=build_admin_export_confirm_keyboard())


@router.callback_query(F.data == CALLBACK_CANCEL, StateFilter(AdminExportTestStates.waiting_confirm))
async def admin_export_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.answer(text=ex.MSG_CANCELLED)


async def _fail_export_and_clear(*, state: FSMContext, message: Message | None) -> None:
    await state.clear()
    if message:
        await message.answer(text=ex.MSG_EXPORT_FAILED)


@router.callback_query(F.data == CALLBACK_CONFIRM, StateFilter(AdminExportTestStates.waiting_confirm))
async def admin_export_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if user is None or callback.message is None:
        await state.clear()
        await callback.answer()
        return
    allowed, err = ex.check_admin_for_export(tg_id=int(user.id))
    if not allowed:
        await state.clear()
        await callback.answer()
        await callback.message.answer(text=err or ex.MSG_NO_PERMISSION)
        return
    if callback.message.chat.type != "private":
        await state.clear()
        await callback.answer()
        await callback.message.answer(text=ex.MSG_NON_PRIVATE)
        return

    data = await state.get_data()
    sid = data.get("export_shift_id")
    start_raw = data.get("export_start_date_iso")
    end_raw = data.get("export_end_date_iso")
    start_d = date.fromisoformat(start_raw) if isinstance(start_raw, str) else None
    end_d = date.fromisoformat(end_raw) if isinstance(end_raw, str) else None
    if not isinstance(sid, int) or start_d is None or end_d is None:
        await callback.answer()
        await _fail_export_and_clear(state=state, message=callback.message)
        return

    files, gen_err = ex.prepare_three_csv_exports(shift_id=int(sid), start_date=start_d, end_date=end_d)
    if gen_err or not files:
        await callback.answer()
        await _fail_export_and_clear(state=state, message=callback.message)
        return

    await callback.answer()
    try:
        for fname, body in files:
            doc = BufferedInputFile(file=body, filename=fname)
            await callback.message.answer_document(document=doc)
    except Exception:
        log.exception("admin_export_test: send CSV failed tg_id=%s", user.id)
        await _fail_export_and_clear(state=state, message=callback.message)
        return

    await state.clear()
