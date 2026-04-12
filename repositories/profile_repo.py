from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional, Sequence

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
class AuditResultLiteRow:
    audit_date: date
    audit_stage: str
    result: str


def list_month_audit_results(
    *,
    employee_id: str,
    shift_id: int,
    month_start_date: date,
    month_end_date: date,
) -> list[AuditResultLiteRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT audit_date, audit_stage, result
            FROM public.audit_results
            WHERE employee_id = %s
              AND shift_id = %s
              AND audit_stage IN ('CHECKIN', 'CHECKOUT')
              AND audit_date >= %s
              AND audit_date <= %s
            ORDER BY audit_date ASC, audit_stage ASC
            """,
            (employee_id, shift_id, month_start_date, month_end_date),
        )
        rows = cur.fetchall() or []
    return [AuditResultLiteRow(*r) for r in rows]


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


@dataclass(frozen=True)
class TemporaryLeaveSpanRow:
    leave_start_at_utc: datetime
    leave_end_at_utc: datetime


def list_effective_temporary_leaves_in_range(
    *,
    employee_id: str,
    shift_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> list[TemporaryLeaveSpanRow]:
    """
    仅用于“我的信息”的 DAILY_ABSENT 推导辅助。
    返回与 [start_utc, end_utc) 有重叠的离岗时段。
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT leave_start_at, leave_end_at
            FROM public.effective_temporary_leaves
            WHERE employee_id = %s
              AND shift_id = %s
              AND leave_start_at < %s
              AND leave_end_at > %s
            ORDER BY leave_start_at ASC
            """,
            (employee_id, shift_id, end_utc, start_utc),
        )
        rows = cur.fetchall() or []
    return [TemporaryLeaveSpanRow(r[0], r[1]) for r in rows]

