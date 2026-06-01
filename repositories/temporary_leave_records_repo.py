from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from infra.db import get_cursor


@dataclass(frozen=True)
class TemporaryLeaveRecordRow:
    id: int
    employee_id: str
    english_name: str
    tg_id: int
    chat_id: int
    leave_at: object
    back_at: object | None
    duration_minutes: int | None
    reason: str | None
    remark_required: bool
    status: str


def ensure_table() -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.temporary_leave_records (
                id BIGSERIAL PRIMARY KEY,
                employee_id VARCHAR(64) NOT NULL,
                english_name VARCHAR(128) NOT NULL,
                tg_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                leave_at TIMESTAMPTZ NOT NULL,
                back_at TIMESTAMPTZ NULL,
                duration_minutes INT NULL,
                reason TEXT NULL,
                remark_required BOOLEAN NOT NULL DEFAULT FALSE,
                status VARCHAR(16) NOT NULL DEFAULT 'OPEN'
            )
            """
        )


def insert_leave(
    *,
    employee_id: str,
    english_name: str,
    tg_id: int,
    chat_id: int,
    leave_at_utc,
    reason: str | None,
) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.temporary_leave_records (
                employee_id, english_name, tg_id, chat_id, leave_at, reason, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'OPEN')
            RETURNING id
            """,
            (str(employee_id), str(english_name), int(tg_id), int(chat_id), leave_at_utc, reason),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError("insert_leave returned no id")
    return int(row[0])


def get_latest_open(*, employee_id: str, chat_id: int) -> Optional[TemporaryLeaveRecordRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, english_name, tg_id, chat_id, leave_at, back_at,
                   duration_minutes, reason, remark_required, status
            FROM public.temporary_leave_records
            WHERE employee_id = %s
              AND chat_id = %s
              AND status = 'OPEN'
            ORDER BY leave_at DESC
            LIMIT 1
            """,
            (str(employee_id), int(chat_id)),
        )
        row = cur.fetchone()
    if not row:
        return None
    return TemporaryLeaveRecordRow(*row)


def list_by_chat_and_range(
    *,
    chat_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> List[TemporaryLeaveRecordRow]:
    """查询与当日 [start_utc, end_utc) 有交集的离岗记录（含跨日未返岗）。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, english_name, tg_id, chat_id, leave_at, back_at,
                   duration_minutes, reason, remark_required, status
            FROM public.temporary_leave_records
            WHERE chat_id = %s
              AND leave_at < %s
              AND (status = 'OPEN' OR back_at IS NULL OR back_at >= %s)
            ORDER BY employee_id ASC, leave_at ASC
            """,
            (int(chat_id), end_utc, start_utc),
        )
        rows = cur.fetchall() or []
    return [TemporaryLeaveRecordRow(*row) for row in rows]


def close_leave(*, record_id: int, back_at_utc, duration_minutes: int, remark_required: bool) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.temporary_leave_records
            SET back_at = %s,
                duration_minutes = %s,
                remark_required = %s,
                status = 'CLOSED'
            WHERE id = %s
            """,
            (back_at_utc, int(duration_minutes), bool(remark_required), int(record_id)),
        )
