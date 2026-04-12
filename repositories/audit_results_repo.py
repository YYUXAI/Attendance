from __future__ import annotations

from typing import Any, Optional

from psycopg2.extensions import cursor as Cursor


def upsert_audit_result(
    cur: Cursor,
    *,
    employee_id: str,
    shift_id: int,
    organization_id: int,
    audit_date,
    audit_stage: str,
    checked_at_utc: Any,
    valid_clock_time_utc: Optional[Any],
    result: str,
) -> None:
    """
    audit_results 幂等 upsert。

    唯一键（docs02）：(employee_id, audit_date, audit_stage, shift_id)
    """
    cur.execute(
        """
        INSERT INTO public.audit_results (
            employee_id,
            shift_id,
            organization_id,
            audit_date,
            audit_stage,
            checked_at,
            valid_clock_time,
            result
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (employee_id, audit_date, audit_stage, shift_id)
        DO UPDATE SET
            organization_id = EXCLUDED.organization_id,
            checked_at = EXCLUDED.checked_at,
            valid_clock_time = EXCLUDED.valid_clock_time,
            result = EXCLUDED.result
        """,
        (
            employee_id,
            shift_id,
            organization_id,
            audit_date,
            audit_stage,
            checked_at_utc,
            valid_clock_time_utc,
            result,
        ),
    )

