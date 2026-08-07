from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from infra.db import get_cursor


ClaimState = Literal["claimed", "completed", "busy"]


@dataclass(frozen=True)
class UpdateClaim:
    state: ClaimState
    claim_token: str | None = None


def claim_update(
    *,
    bot_owner: str,
    update_id: int,
    now: datetime,
    lease_ttl: timedelta,
) -> UpdateClaim:
    claim_token = secrets.token_urlsafe(24)
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.attendance_telegram_update_inbox (
                bot_owner, update_id, status, claim_token, lease_expires_at,
                attempt_count, first_received_at, updated_at,
                completed_at, last_error_code
            ) VALUES (
                %s, %s, 'processing', %s, %s,
                1, %s, %s,
                NULL, NULL
            )
            ON CONFLICT (bot_owner, update_id) DO UPDATE SET
                status = 'processing',
                claim_token = EXCLUDED.claim_token,
                lease_expires_at = EXCLUDED.lease_expires_at,
                attempt_count = public.attendance_telegram_update_inbox.attempt_count + 1,
                updated_at = EXCLUDED.updated_at,
                completed_at = NULL,
                last_error_code = NULL
            WHERE public.attendance_telegram_update_inbox.status = 'failed'
               OR (
                    public.attendance_telegram_update_inbox.status = 'processing'
                    AND public.attendance_telegram_update_inbox.lease_expires_at < EXCLUDED.updated_at
               )
            RETURNING claim_token
            """,
            (
                bot_owner,
                int(update_id),
                claim_token,
                now + lease_ttl,
                now,
                now,
            ),
        )
        row = cur.fetchone()
        if row:
            return UpdateClaim(state="claimed", claim_token=str(row[0]))
        cur.execute(
            """
            SELECT status
            FROM public.attendance_telegram_update_inbox
            WHERE bot_owner = %s AND update_id = %s
            """,
            (bot_owner, int(update_id)),
        )
        existing = cur.fetchone()
        if existing and existing[0] == "completed":
            return UpdateClaim(state="completed")
        return UpdateClaim(state="busy")


def complete_update(
    *,
    bot_owner: str,
    update_id: int,
    claim_token: str,
    now: datetime,
) -> bool:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.attendance_telegram_update_inbox
            SET status = 'completed',
                claim_token = NULL,
                lease_expires_at = NULL,
                updated_at = %s,
                completed_at = %s,
                last_error_code = NULL
            WHERE bot_owner = %s
              AND update_id = %s
              AND status = 'processing'
              AND claim_token = %s
            """,
            (now, now, bot_owner, int(update_id), claim_token),
        )
        return int(cur.rowcount or 0) == 1


def fail_update(
    *,
    bot_owner: str,
    update_id: int,
    claim_token: str,
    error_code: str,
    now: datetime,
) -> bool:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.attendance_telegram_update_inbox
            SET status = 'failed',
                claim_token = NULL,
                lease_expires_at = NULL,
                updated_at = %s,
                completed_at = NULL,
                last_error_code = %s
            WHERE bot_owner = %s
              AND update_id = %s
              AND status = 'processing'
              AND claim_token = %s
            """,
            (
                now,
                str(error_code)[:120],
                bot_owner,
                int(update_id),
                claim_token,
            ),
        )
        return int(cur.rowcount or 0) == 1
