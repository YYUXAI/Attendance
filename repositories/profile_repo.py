from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from infra.db import get_cursor


@dataclass(frozen=True)
class RegistrationProfileRow:
    employee_id: str
    english_name: Optional[str]
    organization_id: Optional[int]
    shift_id: Optional[int]
    department_name: Optional[str]
    leader_employee_id: Optional[str]
    highest_responsible_employee_id: Optional[str]
    checkin_time: Any
    checkout_time: Any
    timezone: Optional[str]


def get_registration_profile_by_tg_id(*, tg_id: int) -> Optional[RegistrationProfileRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.employee_id,
                   r.english_name,
                   r.organization_id,
                   r.shift_id,
                   o.department_name,
                   o.leader_employee_id,
                   o.highest_responsible_employee_id,
                   s.checkin_time,
                   s.checkout_time,
                   s.timezone
            FROM public.registrations r
            LEFT JOIN public.organizations o ON o.id = r.organization_id
            LEFT JOIN public.shifts s ON s.id = r.shift_id
            WHERE r.tg_id = %s
            """,
            (tg_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return RegistrationProfileRow(*row)


def get_employee_english_name_by_employee_id(*, employee_id: str) -> Optional[str]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT english_name
            FROM public.registrations
            WHERE employee_id = %s
            """,
            (employee_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return row[0]


@dataclass(frozen=True)
class EmployeeShiftConfigLite:
    shift_checkin_time: object
    shift_checkout_time: object
    shift_time_range: str
    monthly_rest_days: str


def get_employee_shift_config_for_month(
    *, employee_id: str, year_month: str
) -> Optional[EmployeeShiftConfigLite]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT shift_checkin_time, shift_checkout_time, shift_time_range, monthly_rest_days
            FROM public.employee_shift_config
            WHERE employee_id = %s AND year_month = %s
            """,
            (str(employee_id), str(year_month)),
        )
        row = cur.fetchone()
    if not row:
        return None
    return EmployeeShiftConfigLite(*row)


def list_month_effective_leave_days(
    *,
    employee_id: str,
    shift_id: int,
    month_start_date: date,
    month_end_date: date,
) -> list[date]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT leave_date
            FROM public.effective_leave_days
            WHERE employee_id = %s
              AND shift_id = %s
              AND leave_date >= %s
              AND leave_date <= %s
            ORDER BY leave_date ASC
            """,
            (employee_id, shift_id, month_start_date, month_end_date),
        )
        rows = cur.fetchall() or []
    return [r[0] for r in rows]
