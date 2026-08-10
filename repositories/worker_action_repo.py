from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import psycopg2
from psycopg2.extras import Json

from gateway_provider.contracts import (
    GatewayAsyncActionRequest,
    GatewayDeliveryReceiptRequest,
)


class WorkerActionConflictError(RuntimeError):
    pass


class WorkerActionLeaseLostError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedWorkerAction:
    root_action_id: str
    attempt_action_id: str
    request: dict[str, object]
    lease_owner: str
    attempt_number: int
    acceptance_attempt_count: int


def assert_schema_ready(*, database_url: str) -> None:
    with psycopg2.connect(database_url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    to_regclass('public.attendance_worker_actions'),
                    to_regclass('public.attendance_worker_action_attempts'),
                    to_regclass('public.attendance_gateway_delivery_receipts')
                """
            )
            row = cursor.fetchone()
            if row is None or any(value is None for value in row):
                raise RuntimeError("Attendance durable worker schema is not ready")


def enqueue_action(
    *,
    database_url: str,
    owner_key: str,
    request: dict[str, object],
    max_attempts: int,
    action_kind: str | None = None,
    predecessor_action_id: str | None = None,
) -> Literal["ENQUEUED", "DUPLICATE"]:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            return enqueue_action_cur(
                cursor,
                owner_key=owner_key,
                request=request,
                max_attempts=max_attempts,
                action_kind=action_kind,
                predecessor_action_id=predecessor_action_id,
            )


def enqueue_action_cur(
    cursor: Any,
    *,
    owner_key: str,
    request: dict[str, object],
    max_attempts: int,
    action_kind: str | None = None,
    predecessor_action_id: str | None = None,
) -> Literal["ENQUEUED", "DUPLICATE"]:
    parsed = GatewayAsyncActionRequest.model_validate(request, strict=True)
    if parsed.correlationId is None or parsed.relatedEventId is not None:
        raise ValueError("worker actions require correlationId without relatedEventId")
    if not owner_key.strip() or len(owner_key) > 256:
        raise ValueError("owner_key must contain 1..256 characters")
    if max_attempts < 1 or max_attempts > 20:
        raise ValueError("max_attempts must be between 1 and 20")
    canonical = parsed.model_dump(mode="json", by_alias=True, exclude_none=True)
    resolved_kind = (action_kind or parsed.action.type).strip()
    if not resolved_kind or len(resolved_kind) > 64:
        raise ValueError("action_kind must contain 1..64 characters")
    action_id = parsed.action.actionId
    if predecessor_action_id is not None:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}",
            predecessor_action_id,
        ):
            raise ValueError("predecessor_action_id must be a stable action id")
        if predecessor_action_id == action_id:
            raise ValueError("an action cannot depend on itself")
    created_at = _parse_timestamp(parsed.createdAt)

    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"attendance-worker:{action_id}",),
    )
    cursor.execute(
        """
        SELECT owner_key, action_kind, action_payload, max_attempts,
               predecessor_action_id
        FROM attendance_worker_actions
        WHERE action_id = %s
        """,
        (action_id,),
    )
    existing = cursor.fetchone()
    if existing is not None:
        if existing == (
            owner_key,
            resolved_kind,
            canonical,
            max_attempts,
            predecessor_action_id,
        ):
            return "DUPLICATE"
        raise WorkerActionConflictError(action_id)
    try:
        cursor.execute(
            """
            INSERT INTO attendance_worker_actions (
                action_id, correlation_id, action_kind, owner_key,
                action_payload, status, attempt_count, created_at,
                next_attempt_at, updated_at, max_attempts,
                predecessor_action_id
            ) VALUES (
                %s, %s, %s, %s, %s, 'PENDING', 0, %s, %s, %s, %s, %s
            )
            """,
            (
                action_id,
                parsed.correlationId,
                resolved_kind,
                owner_key,
                Json(canonical),
                created_at,
                created_at,
                created_at,
                max_attempts,
                predecessor_action_id,
            ),
        )
    except psycopg2.errors.UniqueViolation as error:
        raise WorkerActionConflictError(owner_key) from error
    return "ENQUEUED"


def count_actions_for_owner_prefix_cur(cursor: Any, *, owner_prefix: str) -> int:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM attendance_worker_actions
        WHERE LEFT(owner_key, LENGTH(%s)) = %s
        """,
        (owner_prefix, owner_prefix),
    )
    row = cursor.fetchone()
    return 0 if row is None else int(row[0])


def claim_due_actions(
    *,
    database_url: str,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
    limit: int,
) -> list[ClaimedWorkerAction]:
    if not worker_id.strip() or len(worker_id) > 128:
        raise ValueError("worker_id must contain 1..128 characters")
    if lease_seconds < 1 or lease_seconds > 3600:
        raise ValueError("lease_seconds must be between 1 and 3600")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    current = _as_utc(now)
    lease_expires_at = current + timedelta(seconds=lease_seconds)
    claimed: list[ClaimedWorkerAction] = []
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE blocked_actions(action_id) AS (
                    SELECT action_id
                    FROM attendance_worker_actions
                    WHERE status IN ('UNDELIVERABLE', 'UNCERTAIN')
                    UNION ALL
                    SELECT dependent.action_id
                    FROM attendance_worker_actions AS dependent
                    JOIN blocked_actions AS blocked
                      ON dependent.predecessor_action_id = blocked.action_id
                    WHERE dependent.status IN ('PENDING', 'RETRYING')
                )
                UPDATE attendance_worker_actions
                SET status = 'UNDELIVERABLE', terminal_at = %s,
                    next_attempt_at = %s,
                    last_error_code = 'PREDECESSOR_FAILED',
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = %s
                WHERE status IN ('PENDING', 'RETRYING')
                  AND action_id IN (SELECT action_id FROM blocked_actions)
                """,
                (current, current, current),
            )
            cursor.execute(
                """
                SELECT root.action_id, root.correlation_id,
                       root.action_payload, root.status,
                       root.attempt_count, root.last_attempt_action_id
                FROM attendance_worker_actions AS root
                WHERE (
                    (
                        root.status IN ('PENDING', 'RETRYING')
                        AND root.next_attempt_at <= %s
                    ) OR (
                        root.status = 'CLAIMED'
                        AND root.lease_expires_at <= %s
                    )
                ) AND (
                    root.predecessor_action_id IS NULL
                    OR EXISTS (
                        SELECT 1
                        FROM attendance_worker_actions AS predecessor
                        WHERE predecessor.action_id = root.predecessor_action_id
                          AND predecessor.status = 'DELIVERED'
                    )
                )
                ORDER BY root.next_attempt_at, root.created_at, root.action_id
                FOR UPDATE OF root SKIP LOCKED
                LIMIT %s
                """,
                (current, current, limit),
            )
            rows = cursor.fetchall()
            for (
                root_action_id,
                root_correlation_id,
                root_request,
                status,
                attempt_count,
                last_attempt_action_id,
            ) in rows:
                if status in {"PENDING", "RETRYING"}:
                    attempt_number = int(attempt_count) + 1
                    attempt_action_id = _attempt_action_id(
                        root_action_id,
                        attempt_number,
                    )
                    correlation_id = _attempt_correlation_id(
                        root_correlation_id,
                        attempt_number,
                    )
                    attempt_request = copy.deepcopy(root_request)
                    attempt_request["correlationId"] = correlation_id
                    action = dict(attempt_request["action"])
                    action["actionId"] = attempt_action_id
                    attempt_request["action"] = action
                    if attempt_number > 1:
                        attempt_request["createdAt"] = _timestamp(current)
                    GatewayAsyncActionRequest.model_validate(
                        attempt_request,
                        strict=True,
                    )
                    cursor.execute(
                        """
                        INSERT INTO attendance_worker_action_attempts (
                            attempt_action_id, root_action_id, attempt_number,
                            correlation_id, request_payload, status,
                            acceptance_attempt_count, lease_owner,
                            lease_expires_at, created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, 'CLAIMED', 1, %s, %s, %s
                        )
                        """,
                        (
                            attempt_action_id,
                            root_action_id,
                            attempt_number,
                            correlation_id,
                            Json(attempt_request),
                            worker_id,
                            lease_expires_at,
                            current,
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE attendance_worker_actions
                        SET status = 'CLAIMED', attempt_count = %s,
                            last_attempt_action_id = %s,
                            lease_owner = %s, lease_expires_at = %s,
                            last_error_code = NULL, updated_at = %s
                        WHERE action_id = %s
                        """,
                        (
                            attempt_number,
                            attempt_action_id,
                            worker_id,
                            lease_expires_at,
                            current,
                            root_action_id,
                        ),
                    )
                    acceptance_attempt_count = 1
                else:
                    if last_attempt_action_id is None:
                        raise RuntimeError("CLAIMED worker action has no current attempt")
                    cursor.execute(
                        """
                        UPDATE attendance_worker_action_attempts
                        SET status = 'CLAIMED', lease_owner = %s,
                            lease_expires_at = %s,
                            acceptance_attempt_count = acceptance_attempt_count + 1
                        WHERE attempt_action_id = %s
                        RETURNING attempt_number, request_payload,
                                  acceptance_attempt_count
                        """,
                        (worker_id, lease_expires_at, last_attempt_action_id),
                    )
                    attempt = cursor.fetchone()
                    if attempt is None:
                        raise RuntimeError("CLAIMED worker action attempt is missing")
                    attempt_number, attempt_request, acceptance_attempt_count = attempt
                    attempt_action_id = last_attempt_action_id
                    cursor.execute(
                        """
                        UPDATE attendance_worker_actions
                        SET lease_owner = %s, lease_expires_at = %s,
                            updated_at = %s
                        WHERE action_id = %s
                        """,
                        (worker_id, lease_expires_at, current, root_action_id),
                    )
                claimed.append(
                    ClaimedWorkerAction(
                        root_action_id=root_action_id,
                        attempt_action_id=attempt_action_id,
                        request=attempt_request,
                        lease_owner=worker_id,
                        attempt_number=int(attempt_number),
                        acceptance_attempt_count=int(acceptance_attempt_count),
                    )
                )
    return claimed


def mark_submitted(
    *,
    database_url: str,
    claim: ClaimedWorkerAction,
    submitted_at: datetime,
) -> None:
    current = _as_utc(submitted_at)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE attendance_worker_actions
                SET status = 'SUBMITTED', submitted_at = COALESCE(submitted_at, %s),
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = NULL, updated_at = %s
                WHERE action_id = %s AND status = 'CLAIMED'
                  AND lease_owner = %s AND last_attempt_action_id = %s
                """,
                (
                    current,
                    current,
                    claim.root_action_id,
                    claim.lease_owner,
                    claim.attempt_action_id,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkerActionLeaseLostError(claim.root_action_id)
            cursor.execute(
                """
                UPDATE attendance_worker_action_attempts
                SET status = 'SUBMITTED', submitted_at = COALESCE(submitted_at, %s),
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = NULL
                WHERE attempt_action_id = %s AND lease_owner = %s
                """,
                (current, claim.attempt_action_id, claim.lease_owner),
            )
            if cursor.rowcount != 1:
                raise WorkerActionLeaseLostError(claim.attempt_action_id)


def mark_acceptance_retry(
    *,
    database_url: str,
    claim: ClaimedWorkerAction,
    error_code: str,
    now: datetime,
    retry_seconds: int,
    maximum_acceptance_attempts: int,
) -> None:
    current = _as_utc(now)
    if claim.acceptance_attempt_count >= maximum_acceptance_attempts:
        mark_acceptance_terminal(
            database_url=database_url,
            claim=claim,
            error_code="GATEWAY_ACCEPTANCE_RETRY_EXHAUSTED",
            now=current,
            uncertain=True,
        )
        return
    retry_at = current + timedelta(seconds=retry_seconds)
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE attendance_worker_actions
                SET status = 'CLAIMED', lease_owner = NULL,
                    lease_expires_at = %s, next_attempt_at = %s,
                    last_error_code = %s, updated_at = %s
                WHERE action_id = %s AND status = 'CLAIMED'
                  AND lease_owner = %s AND last_attempt_action_id = %s
                """,
                (
                    retry_at,
                    retry_at,
                    error_code,
                    current,
                    claim.root_action_id,
                    claim.lease_owner,
                    claim.attempt_action_id,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkerActionLeaseLostError(claim.root_action_id)
            cursor.execute(
                """
                UPDATE attendance_worker_action_attempts
                SET status = 'ACCEPTANCE_RETRY', lease_owner = NULL,
                    lease_expires_at = %s, last_error_code = %s
                WHERE attempt_action_id = %s AND lease_owner = %s
                """,
                (retry_at, error_code, claim.attempt_action_id, claim.lease_owner),
            )
            if cursor.rowcount != 1:
                raise WorkerActionLeaseLostError(claim.attempt_action_id)


def mark_acceptance_terminal(
    *,
    database_url: str,
    claim: ClaimedWorkerAction,
    error_code: str,
    now: datetime,
    uncertain: bool = False,
) -> None:
    current = _as_utc(now)
    terminal_status = "UNCERTAIN" if uncertain else "UNDELIVERABLE"
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE attendance_worker_actions
                SET status = %s, terminal_at = %s, lease_owner = NULL,
                    lease_expires_at = NULL, last_error_code = %s,
                    updated_at = %s
                WHERE action_id = %s AND status = 'CLAIMED'
                  AND lease_owner = %s AND last_attempt_action_id = %s
                """,
                (
                    terminal_status,
                    current,
                    error_code,
                    current,
                    claim.root_action_id,
                    claim.lease_owner,
                    claim.attempt_action_id,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkerActionLeaseLostError(claim.root_action_id)
            cursor.execute(
                """
                UPDATE attendance_worker_action_attempts
                SET status = %s, terminal_at = %s, lease_owner = NULL,
                    lease_expires_at = NULL, last_error_code = %s
                WHERE attempt_action_id = %s AND lease_owner = %s
                """,
                (
                    terminal_status,
                    current,
                    error_code,
                    claim.attempt_action_id,
                    claim.lease_owner,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkerActionLeaseLostError(claim.attempt_action_id)


def apply_delivery_receipt_cur(
    cursor: Any,
    *,
    receipt: GatewayDeliveryReceiptRequest,
    processed_at: datetime,
) -> bool:
    if receipt.correlationId is None:
        return False
    cursor.execute(
        """
        SELECT attempt.root_action_id, attempt.attempt_number,
               root.attempt_count, root.max_attempts,
               root.action_kind, root.owner_key
        FROM attendance_worker_action_attempts AS attempt
        JOIN attendance_worker_actions AS root
          ON root.action_id = attempt.root_action_id
        WHERE attempt.attempt_action_id = %s
          AND attempt.correlation_id = %s
        FOR UPDATE OF attempt, root
        """,
        (receipt.actionId, receipt.correlationId),
    )
    row = cursor.fetchone()
    if row is None:
        return False
    (
        root_action_id,
        attempt_number,
        attempt_count,
        max_attempts,
        action_kind,
        owner_key,
    ) = row
    failure_code = receipt.failure.code if receipt.failure is not None else None
    retryable = (
        receipt.status == "PERMANENTLY_FAILED"
        and failure_code in {"RATE_LIMIT_EXHAUSTED", "TELEGRAM_ERROR"}
    ) or (
        receipt.status == "SUPERSEDED" and failure_code == "ACTION_EXPIRED"
    )
    if receipt.status == "DELIVERED":
        root_status = "DELIVERED"
        attempt_status = "DELIVERED"
    elif receipt.status == "UNCERTAIN":
        root_status = "UNCERTAIN"
        attempt_status = "UNCERTAIN"
    elif retryable and int(attempt_count) < int(max_attempts):
        root_status = "RETRYING"
        attempt_status = "UNDELIVERABLE"
    else:
        root_status = "UNDELIVERABLE"
        attempt_status = "UNDELIVERABLE"
    terminal_at = processed_at if root_status != "RETRYING" else None
    next_attempt_at = (
        processed_at + timedelta(seconds=_delivery_retry_seconds(int(attempt_number)))
        if root_status == "RETRYING"
        else processed_at
    )
    cursor.execute(
        """
        UPDATE attendance_worker_action_attempts
        SET status = %s, terminal_at = %s, last_error_code = %s,
            lease_owner = NULL, lease_expires_at = NULL
        WHERE attempt_action_id = %s
        """,
        (attempt_status, processed_at, failure_code, receipt.actionId),
    )
    cursor.execute(
        """
        UPDATE attendance_worker_actions
        SET status = %s, terminal_at = %s, next_attempt_at = %s,
            last_error_code = %s, last_receipt_id = %s,
            lease_owner = NULL, lease_expires_at = NULL,
            updated_at = %s
        WHERE action_id = %s AND last_attempt_action_id = %s
        """,
        (
            root_status,
            terminal_at,
            next_attempt_at,
            failure_code,
            receipt.receiptId,
            processed_at,
            root_action_id,
            receipt.actionId,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("worker receipt does not match current action attempt")
    if root_status == "DELIVERED" and action_kind == "DAILY_REPORT":
        report_date = datetime.fromisoformat(owner_key).date()
        cursor.execute(
            """
            INSERT INTO attendance_daily_report_ledger (
                report_date, action_id, delivered_at
            ) VALUES (%s, %s, %s)
            ON CONFLICT (report_date) DO NOTHING
            """,
            (report_date, root_action_id, processed_at),
        )
    return True


def _attempt_action_id(root_action_id: str, attempt_number: int) -> str:
    if attempt_number == 1:
        return root_action_id
    suffix = f".retry.{attempt_number}"
    if len(root_action_id) + len(suffix) <= 128:
        return f"{root_action_id}{suffix}"
    digest = hashlib.sha256(root_action_id.encode("utf-8")).hexdigest()[:16]
    resolved_suffix = f".retry.{attempt_number}.{digest}"
    return f"{root_action_id[:128 - len(resolved_suffix)]}{resolved_suffix}"


def _attempt_correlation_id(root_correlation_id: str, attempt_number: int) -> str:
    if attempt_number == 1:
        return root_correlation_id
    suffix = f".retry.{attempt_number}"
    if len(root_correlation_id) + len(suffix) <= 256:
        return f"{root_correlation_id}{suffix}"
    digest = hashlib.sha256(root_correlation_id.encode("utf-8")).hexdigest()[:16]
    resolved_suffix = f".retry.{attempt_number}.{digest}"
    return f"{root_correlation_id[:256 - len(resolved_suffix)]}{resolved_suffix}"


def _delivery_retry_seconds(attempt_number: int) -> int:
    return min(300, 5 * (2 ** max(0, attempt_number - 1)))


def _parse_timestamp(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _as_utc(value: datetime) -> datetime:
    current = value
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("datetime must include a UTC offset")
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")
