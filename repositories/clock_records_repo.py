from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from infra.db import get_cursor


@dataclass(frozen=True)
class ClockRecordRow:
    id: int
    employee_id: str
    shift_id: int
    clock_time: Any


def insert_clock_record(
    *,
    chat_id: int,
    file_id: str,
    tg_id: int,
    employee_id: str,
    shift_id: int,
    clock_time_utc,
) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.clock_records
                (chat_id, file_id, tg_id, employee_id, shift_id, clock_time)
            VALUES
                (%s, %s, %s, %s, %s, %s)
            """,
            (chat_id, file_id, tg_id, employee_id, shift_id, clock_time_utc),
        )


def list_clock_records_in_range(
    *,
    employee_id: str,
    shift_id: int,
    start_at_utc: Any,
    end_at_utc: Any,
) -> List[ClockRecordRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, shift_id, clock_time
            FROM public.clock_records
            WHERE employee_id = %s
              AND shift_id = %s
              AND clock_time >= %s
              AND clock_time < %s
            ORDER BY clock_time ASC
            """,
            (employee_id, shift_id, start_at_utc, end_at_utc),
        )
        rows = cur.fetchall()
    return [ClockRecordRow(*r) for r in rows]
