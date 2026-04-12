from __future__ import annotations

from datetime import date, datetime
from typing import Any, Union

from psycopg2.extensions import cursor as Cursor


def _work_date_from_effective_date(effective_date: Union[date, datetime]) -> date:
    """effective_temporary_leaves.effective_date：date 直接用；带时间则取日期部分。"""
    if isinstance(effective_date, datetime):
        return effective_date.date()
    return effective_date


def upsert_from_effective_row(
    cur: Cursor,
    *,
    shift_id: int,
    employee_id: str,
    effective_date: Union[date, datetime],
    exemption_start_at: Any,
    exemption_end_at: Any,
    source_effective_temporary_leave_id: int,
    updated_at_utc: Any,
) -> None:
    """
    由 effective_temporary_leaves 派生写入临时免检覆盖表。
    幂等：ON CONFLICT (source_effective_temporary_leave_id) DO UPDATE，禁止依赖唯一键报错当业务分支。
    """
    work_date = _work_date_from_effective_date(effective_date)
    cur.execute(
        """
        INSERT INTO public.temporary_qc_exemption_list (
            shift_id,
            employee_id,
            work_date,
            exemption_start_at,
            exemption_end_at,
            source_effective_temporary_leave_id,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_effective_temporary_leave_id)
        DO UPDATE SET
            shift_id = EXCLUDED.shift_id,
            employee_id = EXCLUDED.employee_id,
            work_date = EXCLUDED.work_date,
            exemption_start_at = EXCLUDED.exemption_start_at,
            exemption_end_at = EXCLUDED.exemption_end_at,
            updated_at = EXCLUDED.updated_at
        """,
        (
            shift_id,
            employee_id,
            work_date,
            exemption_start_at,
            exemption_end_at,
            source_effective_temporary_leave_id,
            updated_at_utc,
        ),
    )


def delete_by_source_effective_temporary_leave_id(
    cur: Cursor,
    *,
    source_effective_temporary_leave_id: int,
) -> int:
    """按来源 effective 行精确删除；0 行视为正常（幂等）。"""
    cur.execute(
        """
        DELETE FROM public.temporary_qc_exemption_list
        WHERE source_effective_temporary_leave_id = %s
        """,
        (int(source_effective_temporary_leave_id),),
    )
    return int(cur.rowcount)
