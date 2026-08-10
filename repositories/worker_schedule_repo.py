from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import psycopg2
from psycopg2.extensions import cursor as Cursor
from psycopg2.extras import Json


@dataclass(frozen=True)
class ClaimedScheduleRun:
    lease_version: int


@dataclass(frozen=True)
class DueScheduleRun:
    run_key: str
    payload: dict[str, Any]


def assert_schema_ready(*, database_url: str) -> None:
    with psycopg2.connect(database_url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.attendance_worker_schedule_runs')"
            )
            if cursor.fetchone() != ("attendance_worker_schedule_runs",):
                raise RuntimeError("Attendance scheduler schema is not ready")


def list_due_run_dates(
    *,
    database_url: str,
    job_kind: str,
    run_key_prefix: str,
    through_date: date,
) -> tuple[date, ...]:
    if not job_kind.strip() or len(job_kind) > 64:
        raise ValueError("job_kind must contain 1..64 characters")
    if not run_key_prefix or len(run_key_prefix) > 240:
        raise ValueError("run_key_prefix must contain 1..240 characters")
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run_key, status
                FROM attendance_worker_schedule_runs
                WHERE job_kind = %s
                  AND LEFT(run_key, LENGTH(%s)) = %s
                ORDER BY run_key
                """,
                (job_kind, run_key_prefix, run_key_prefix),
            )
            rows = cursor.fetchall()
    recorded: dict[date, str] = {}
    for raw_key, raw_status in rows:
        suffix = str(raw_key)[len(run_key_prefix) :]
        try:
            run_date = date.fromisoformat(suffix)
        except ValueError as error:
            raise RuntimeError(
                f"invalid persisted scheduler date key: {raw_key}"
            ) from error
        if run_date <= through_date:
            recorded[run_date] = str(raw_status)
    if not recorded:
        return (through_date,)
    cursor_date = min(recorded)
    due: list[date] = []
    while cursor_date <= through_date:
        if recorded.get(cursor_date) != "COMPLETED":
            due.append(cursor_date)
        cursor_date += timedelta(days=1)
    return tuple(due)


def is_run_completed(*, database_url: str, run_key: str) -> bool:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status
                FROM attendance_worker_schedule_runs
                WHERE run_key = %s
                """,
                (run_key,),
            )
            row = cursor.fetchone()
    return row is not None and str(row[0]) == "COMPLETED"


def event_action_delivery_status(
    *,
    database_url: str,
    event_id: str,
    action_id: str,
) -> str | None:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status
                FROM attendance_gateway_delivery_receipts
                WHERE related_event_id = %s AND action_id = %s
                """,
                (event_id, action_id),
            )
            row = cursor.fetchone()
    return None if row is None else str(row[0])


def event_action_delivered_message_id(
    *,
    database_url: str,
    event_id: str,
    action_id: str,
) -> int | None:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT CASE
                    WHEN status = 'DELIVERED'
                     AND jsonb_typeof(
                         receipt_payload->'telegramResult'->'messageId'
                     ) = 'number'
                    THEN (receipt_payload->'telegramResult'->>'messageId')::bigint
                    ELSE NULL
                END
                FROM attendance_gateway_delivery_receipts
                WHERE related_event_id = %s AND action_id = %s
                """,
                (event_id, action_id),
            )
            row = cursor.fetchone()
    return None if row is None or row[0] is None else int(row[0])


def fail_waiting_run(
    *,
    database_url: str,
    run_key: str,
    job_kind: str,
    error_code: str,
    now: datetime,
) -> bool:
    _validate_identity(run_key=run_key, job_kind=job_kind)
    if not error_code.strip() or len(error_code) > 128:
        raise ValueError("error_code must contain 1..128 characters")
    current = _as_utc(now)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"attendance-schedule:{run_key}",),
            )
            cursor.execute(
                """
                UPDATE attendance_worker_schedule_runs
                SET status = 'FAILED', lease_owner = NULL,
                    lease_expires_at = NULL, completed_at = %s,
                    last_error_code = %s, updated_at = %s
                WHERE run_key = %s AND job_kind = %s
                  AND status IN ('PENDING', 'RETRYING')
                """,
                (current, error_code, current, run_key, job_kind),
            )
            return cursor.rowcount == 1


def enqueue_run_cur(
    cursor: Cursor,
    *,
    run_key: str,
    job_kind: str,
    payload: dict[str, object],
    now: datetime,
) -> bool:
    _validate_identity(run_key=run_key, job_kind=job_kind)
    current = _as_utc(now)
    cursor.execute(
        """
        INSERT INTO attendance_worker_schedule_runs (
            run_key, job_kind, status, attempt_count, payload,
            lease_version, next_attempt_at, created_at, updated_at
        ) VALUES (%s, %s, 'PENDING', 0, %s, 0, %s, %s, %s)
        ON CONFLICT (run_key) DO NOTHING
        RETURNING run_key
        """,
        (run_key, job_kind, Json(payload), current, current, current),
    )
    return cursor.fetchone() is not None


def list_due_runs(
    *,
    database_url: str,
    job_kind: str,
    run_key_prefix: str,
    now: datetime,
    limit: int,
) -> tuple[DueScheduleRun, ...]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    _validate_identity(run_key=run_key_prefix, job_kind=job_kind)
    current = _as_utc(now)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run_key, payload
                FROM attendance_worker_schedule_runs
                WHERE job_kind = %s
                  AND LEFT(run_key, LENGTH(%s)) = %s
                  AND (
                    (status IN ('PENDING', 'RETRYING') AND next_attempt_at <= %s)
                    OR (status = 'PROCESSING' AND lease_expires_at <= %s)
                  )
                ORDER BY next_attempt_at, created_at, run_key
                LIMIT %s
                """,
                (job_kind, run_key_prefix, run_key_prefix, current, current, limit),
            )
            rows = cursor.fetchall()
    return tuple(
        DueScheduleRun(run_key=str(run_key), payload=dict(payload))
        for run_key, payload in rows
    )


def claim_run(
    *,
    database_url: str,
    run_key: str,
    job_kind: str,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> ClaimedScheduleRun | None:
    _validate_identity(run_key=run_key, job_kind=job_kind)
    if not worker_id.strip() or len(worker_id) > 128:
        raise ValueError("worker_id must contain 1..128 characters")
    current = _as_utc(now)
    lease_expires_at = current + timedelta(seconds=lease_seconds)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"attendance-schedule:{run_key}",),
            )
            cursor.execute(
                """
                SELECT job_kind, status, lease_expires_at, next_attempt_at,
                       lease_version
                FROM attendance_worker_schedule_runs
                WHERE run_key = %s
                FOR UPDATE
                """,
                (run_key,),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    INSERT INTO attendance_worker_schedule_runs (
                        run_key, job_kind, status, attempt_count,
                        lease_owner, lease_expires_at, next_attempt_at,
                        created_at, updated_at, lease_version
                    ) VALUES (%s, %s, 'PROCESSING', 1, %s, %s, %s, %s, %s, 1)
                    RETURNING lease_version
                    """,
                    (
                        run_key,
                        job_kind,
                        worker_id,
                        lease_expires_at,
                        current,
                        current,
                        current,
                    ),
                )
                return ClaimedScheduleRun(lease_version=int(cursor.fetchone()[0]))
            existing_kind, status, existing_lease, next_attempt_at, _lease_version = row
            if str(existing_kind) != job_kind:
                raise RuntimeError("scheduler run key belongs to another job kind")
            if str(status) in {"COMPLETED", "FAILED"}:
                return None
            if str(status) == "PROCESSING" and existing_lease > current:
                return None
            if next_attempt_at > current:
                return None
            cursor.execute(
                """
                UPDATE attendance_worker_schedule_runs
                SET status = 'PROCESSING',
                    attempt_count = attempt_count + 1,
                    lease_owner = %s,
                    lease_expires_at = %s,
                    lease_version = lease_version + 1,
                    last_error_code = NULL,
                    updated_at = %s
                WHERE run_key = %s
                RETURNING lease_version
                """,
                (worker_id, lease_expires_at, current, run_key),
            )
            claimed = cursor.fetchone()
            if claimed is None:
                return None
            return ClaimedScheduleRun(lease_version=int(claimed[0]))


def renew_run(
    *,
    database_url: str,
    run_key: str,
    worker_id: str,
    lease_version: int,
    now: datetime,
    lease_seconds: int,
) -> bool:
    current = _as_utc(now)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE attendance_worker_schedule_runs
                SET lease_expires_at = %s, updated_at = %s
                WHERE run_key = %s AND status = 'PROCESSING'
                  AND lease_owner = %s AND lease_version = %s
                  AND lease_expires_at > %s
                """,
                (
                    current + timedelta(seconds=lease_seconds),
                    current,
                    run_key,
                    worker_id,
                    lease_version,
                    current,
                ),
            )
            return cursor.rowcount == 1


def complete_run(
    *,
    database_url: str,
    run_key: str,
    worker_id: str,
    lease_version: int,
    now: datetime,
) -> None:
    current = _as_utc(now)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE attendance_worker_schedule_runs
                SET status = 'COMPLETED', lease_owner = NULL,
                    lease_expires_at = NULL, completed_at = %s,
                    updated_at = %s
                WHERE run_key = %s AND status = 'PROCESSING'
                  AND lease_owner = %s AND lease_version = %s
                """,
                (current, current, run_key, worker_id, lease_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("scheduler lease was lost before completion")


def retry_run(
    *,
    database_url: str,
    run_key: str,
    worker_id: str,
    lease_version: int,
    now: datetime,
    error_code: str,
    retry_seconds: int = 60,
) -> None:
    current = _as_utc(now)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE attendance_worker_schedule_runs
                SET status = 'RETRYING', lease_owner = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = %s,
                    last_error_code = %s,
                    updated_at = %s
                WHERE run_key = %s AND status = 'PROCESSING'
                  AND lease_owner = %s AND lease_version = %s
                """,
                (
                    current + timedelta(seconds=retry_seconds),
                    error_code[:128],
                    current,
                    run_key,
                    worker_id,
                    lease_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("scheduler lease was lost before retry")


def _validate_identity(*, run_key: str, job_kind: str) -> None:
    if not run_key.strip() or len(run_key) > 256:
        raise ValueError("run_key must contain 1..256 characters")
    if not job_kind.strip() or len(job_kind) > 64:
        raise ValueError("job_kind must contain 1..64 characters")


def _as_utc(value: datetime) -> datetime:
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)
