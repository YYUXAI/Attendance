from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import List, Optional

from infra.db import get_cursor


@dataclass(frozen=True)
class EmployeeShiftConfigRow:
    id: int
    year_month: str
    employee_id: str
    english_name: str
    shift_time_range: str
    shift_checkin_time: time
    shift_checkout_time: time
    monthly_rest_days: str
    updated_at: object


def ensure_table() -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.employee_shift_config (
                id BIGSERIAL PRIMARY KEY,
                year_month VARCHAR(7) NOT NULL DEFAULT '2026-05',
                employee_id VARCHAR(64) NOT NULL,
                english_name VARCHAR(128) NOT NULL,
                shift_time_range VARCHAR(64) NOT NULL,
                shift_checkin_time TIME NOT NULL,
                shift_checkout_time TIME NOT NULL,
                monthly_rest_days VARCHAR(128) NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        # 旧表仅有 employee_id 唯一时，迁移为 (year_month, employee_id)
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'employee_shift_config'
                      AND column_name = 'year_month'
                ) THEN
                    ALTER TABLE public.employee_shift_config
                    ADD COLUMN year_month VARCHAR(7) NOT NULL DEFAULT '2026-05';
                END IF;
            END $$;
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'employee_shift_config_employee_id_key'
                ) THEN
                    ALTER TABLE public.employee_shift_config
                    DROP CONSTRAINT employee_shift_config_employee_id_key;
                END IF;
            EXCEPTION WHEN undefined_object THEN
                NULL;
            END $$;
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_shift_config_month_employee
            ON public.employee_shift_config (year_month, employee_id)
            """
        )


def upsert_config(
    *,
    year_month: str,
    employee_id: str,
    english_name: str,
    shift_time_range: str,
    shift_checkin_time,
    shift_checkout_time,
    monthly_rest_days: str,
) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.employee_shift_config (
                year_month, employee_id, english_name, shift_time_range,
                shift_checkin_time, shift_checkout_time, monthly_rest_days, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (year_month, employee_id)
            DO UPDATE SET
                english_name = EXCLUDED.english_name,
                shift_time_range = EXCLUDED.shift_time_range,
                shift_checkin_time = EXCLUDED.shift_checkin_time,
                shift_checkout_time = EXCLUDED.shift_checkout_time,
                monthly_rest_days = EXCLUDED.monthly_rest_days,
                updated_at = NOW()
            """,
            (
                str(year_month),
                str(employee_id),
                str(english_name),
                str(shift_time_range),
                shift_checkin_time,
                shift_checkout_time,
                str(monthly_rest_days or ""),
            ),
        )


def get_by_employee_id(
    *, year_month: str, employee_id: str
) -> Optional[EmployeeShiftConfigRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, year_month, employee_id, english_name, shift_time_range,
                   shift_checkin_time, shift_checkout_time, monthly_rest_days, updated_at
            FROM public.employee_shift_config
            WHERE year_month = %s AND employee_id = %s
            """,
            (str(year_month), str(employee_id)),
        )
        row = cur.fetchone()
    if not row:
        return None
    return EmployeeShiftConfigRow(*row)


def list_by_year_month(*, year_month: str) -> List[EmployeeShiftConfigRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, year_month, employee_id, english_name, shift_time_range,
                   shift_checkin_time, shift_checkout_time, monthly_rest_days, updated_at
            FROM public.employee_shift_config
            WHERE year_month = %s
            ORDER BY CAST(employee_id AS BIGINT)
            """,
            (str(year_month),),
        )
        rows = cur.fetchall() or []
    return [EmployeeShiftConfigRow(*r) for r in rows]


def delete_not_in(*, year_month: str, employee_ids: list[str]) -> int:
    """删除该月不在 employee_ids 列表中的配置（全量同步保存/导入后用）。"""
    with get_cursor() as cur:
        if employee_ids:
            cur.execute(
                """
                DELETE FROM public.employee_shift_config
                WHERE year_month = %s
                  AND employee_id <> ALL(%s::varchar[])
                """,
                (str(year_month), [str(x) for x in employee_ids]),
            )
        else:
            cur.execute(
                """
                DELETE FROM public.employee_shift_config
                WHERE year_month = %s
                """,
                (str(year_month),),
            )
        return int(cur.rowcount or 0)


def list_all() -> List[EmployeeShiftConfigRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, year_month, employee_id, english_name, shift_time_range,
                   shift_checkin_time, shift_checkout_time, monthly_rest_days, updated_at
            FROM public.employee_shift_config
            ORDER BY year_month DESC, CAST(employee_id AS BIGINT)
            """
        )
        rows = cur.fetchall() or []
    return [EmployeeShiftConfigRow(*r) for r in rows]
