from __future__ import annotations

from infra.db import get_cursor


def ensure_table() -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.employee_shift_roster (
                year_month VARCHAR(7) NOT NULL,
                source VARCHAR(16) NOT NULL,
                employee_id VARCHAR(64) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (year_month, source, employee_id)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_employee_shift_roster_month_source
            ON public.employee_shift_roster (year_month, source)
            """
        )


def set_roster(*, year_month: str, source: str, employee_ids: list[str]) -> None:
    src = (source or "").strip().lower()
    ym = str(year_month).strip()
    ids = [str(x).strip() for x in employee_ids if str(x).strip()]
    ensure_table()
    with get_cursor() as cur:
        cur.execute(
            """
            DELETE FROM public.employee_shift_roster
            WHERE year_month = %s AND source = %s
            """,
            (ym, src),
        )
        if ids:
            cur.executemany(
                """
                INSERT INTO public.employee_shift_roster (year_month, source, employee_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (year_month, source, employee_id) DO NOTHING
                """,
                [(ym, src, eid) for eid in ids],
            )


def list_roster(*, year_month: str, source: str) -> list[str]:
    src = (source or "").strip().lower()
    ym = str(year_month).strip()
    ensure_table()
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT employee_id
            FROM public.employee_shift_roster
            WHERE year_month = %s AND source = %s
            ORDER BY CAST(employee_id AS BIGINT)
            """,
            (ym, src),
        )
        rows = cur.fetchall() or []
    return [str(r[0]) for r in rows if r and r[0]]


def roster_set(*, year_month: str, source: str) -> frozenset[str]:
    return frozenset(list_roster(year_month=year_month, source=source))
