from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from infra.db import get_cursor


@dataclass(frozen=True)
class ShiftRow:
    id: int
    checkin_time: object
    checkout_time: object
    timezone: str
    is_overnight: bool
    attendance_group_id: int | None
    attendance_flex_interval: object
    max_late_early_tolerance: object


def get_by_id(shift_id: int) -> Optional[ShiftRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, checkin_time, checkout_time, timezone, is_overnight, attendance_group_id,
                   attendance_flex_interval, max_late_early_tolerance
            FROM public.shifts
            WHERE id = %s
            """,
            (shift_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return ShiftRow(*row)


def list_all_shifts() -> List[ShiftRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, checkin_time, checkout_time, timezone, is_overnight, attendance_group_id,
                   attendance_flex_interval, max_late_early_tolerance
            FROM public.shifts
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
    return [ShiftRow(*r) for r in rows]


def list_by_attendance_group_id(*, attendance_group_id: int) -> List[ShiftRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, checkin_time, checkout_time, timezone, is_overnight, attendance_group_id,
                   attendance_flex_interval, max_late_early_tolerance
            FROM public.shifts
            WHERE attendance_group_id = %s
            ORDER BY id ASC
            """,
            (int(attendance_group_id),),
        )
        rows = cur.fetchall() or []
    return [ShiftRow(*r) for r in rows]
