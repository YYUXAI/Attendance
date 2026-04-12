from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminExportTestStates(StatesGroup):
    waiting_shift_id = State()
    waiting_start_date = State()
    waiting_end_date = State()
    waiting_confirm = State()
