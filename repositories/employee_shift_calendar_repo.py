from __future__ import annotations

from datetime import date
from typing import Iterable

from infra.db import get_cursor


def ensure_table() -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.employee_shift_calendar (
                id BIGSERIAL PRIMARY KEY,
                year_month VARCHAR(7) NOT NULL,
                employee_id VARCHAR(64) NOT NULL,
                work_date DATE NOT NULL,
                cell_raw TEXT NOT NULL DEFAULT '',
                shift_code VARCHAR(16) NOT NULL DEFAULT '',
                cell_kind VARCHAR(16) NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_shift_calendar
            ON public.employee_shift_calendar (year_month, employee_id, work_date)
            """
        )


def upsert_many(
    *,
    year_month: str,
    rows: Iterable[tuple[str, date, str, str, str]],
) -> int:
    payload = list(rows)
    if not payload:
        return 0
    with get_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.employee_shift_calendar
                (year_month, employee_id, work_date, cell_raw, shift_code, cell_kind, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (year_month, employee_id, work_date)
            DO UPDATE SET
                cell_raw = EXCLUDED.cell_raw,
                shift_code = EXCLUDED.shift_code,
                cell_kind = EXCLUDED.cell_kind,
                updated_at = NOW()
            """,
            [(year_month, eid, wd, raw, code, kind) for eid, wd, raw, code, kind in payload],
        )
    return len(payload)


def delete_not_in(*, year_month: str, employee_ids: Iterable[str]) -> int:
    ids = list(employee_ids)
    with get_cursor() as cur:
        if not ids:
            cur.execute(
                "DELETE FROM public.employee_shift_calendar WHERE year_month = %s",
                (year_month,),
            )
        else:
            cur.execute(
                """
                DELETE FROM public.employee_shift_calendar
                WHERE year_month = %s AND employee_id <> ALL(%s::varchar[])
                """,
                (year_month, ids),
            )
        return int(cur.rowcount or 0)
