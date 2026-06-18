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
    clock_action: str | None = None


def ensure_clock_action_column() -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'clock_records'
                      AND column_name = 'clock_action'
                ) THEN
                    ALTER TABLE public.clock_records
                    ADD COLUMN clock_action VARCHAR(16);
                END IF;
            END $$;
            """
        )


def insert_clock_record(
    *,
    chat_id: int,
    file_id: str,
    tg_id: int,
    employee_id: str,
    shift_id: int | None,
    clock_time_utc,
    clock_action: str | None = None,
) -> None:
    ensure_clock_action_column()
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.clock_records
                (chat_id, file_id, tg_id, employee_id, shift_id, clock_time, clock_action)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
            """,
            (chat_id, file_id, tg_id, employee_id, shift_id, clock_time_utc, clock_action),
        )


def get_latest_chat_id_for_employee(*, employee_id: str) -> int | None:
    """最近一条打卡所在群，用于无 shift_id 时的个人统计。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT chat_id
            FROM public.clock_records
            WHERE employee_id = %s
            ORDER BY clock_time DESC
            LIMIT 1
            """,
            (str(employee_id),),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def list_clock_records_by_employee_chat_in_range(
    *,
    employee_id: str,
    chat_id: int,
    start_at_utc: Any,
    end_at_utc: Any,
) -> List[ClockRecordRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, shift_id, clock_time, clock_action
            FROM public.clock_records
            WHERE employee_id = %s
              AND chat_id = %s
              AND clock_time >= %s
              AND clock_time < %s
            ORDER BY clock_time ASC
            """,
            (str(employee_id), int(chat_id), start_at_utc, end_at_utc),
        )
        rows = cur.fetchall() or []
    return [ClockRecordRow(*r) for r in rows]


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
            SELECT id, employee_id, shift_id, clock_time, clock_action
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


def list_distinct_employee_ids_for_shift_in_range(
    *,
    shift_id: int,
    start_at_utc: Any,
    end_at_utc: Any,
) -> List[str]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT employee_id
            FROM public.clock_records
            WHERE shift_id = %s
              AND clock_time >= %s
              AND clock_time < %s
            ORDER BY employee_id ASC
            """,
            (shift_id, start_at_utc, end_at_utc),
        )
        rows = cur.fetchall() or []
    return [str(r[0]) for r in rows if r and r[0] is not None]


def list_clock_times_for_shift_employees_in_range(
    *,
    shift_id: int,
    employee_ids: List[str],
    start_at_utc: Any,
    end_at_utc: Any,
) -> List[ClockRecordRow]:
    if not employee_ids:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, shift_id, clock_time, clock_action
            FROM public.clock_records
            WHERE shift_id = %s
              AND employee_id = ANY(%s)
              AND clock_time >= %s
              AND clock_time < %s
            ORDER BY employee_id ASC, clock_time ASC
            """,
            (shift_id, employee_ids, start_at_utc, end_at_utc),
        )
        rows = cur.fetchall() or []
    return [ClockRecordRow(*r) for r in rows]
