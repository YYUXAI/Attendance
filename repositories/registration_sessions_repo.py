from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from psycopg2.extensions import cursor as Cursor

from repositories import registrations_repo


RegistrationStage = Literal["awaiting_input", "awaiting_confirmation"]
ConfirmResultCode = Literal[
    "ok",
    "expired",
    "owner_mismatch",
    "tg_already_bound",
    "employee_not_pre_registered",
    "employee_already_bound",
    "employee_name_mismatch",
]


@dataclass(frozen=True)
class RegistrationSessionRow:
    tg_id: int
    private_chat_id: int
    stage: RegistrationStage
    english_name: str | None
    employee_id: str | None
    created_at: datetime
    last_activity_at: datetime
    inactivity_expires_at: datetime
    absolute_expires_at: datetime
    preview_expires_at: datetime | None


@dataclass(frozen=True)
class ConfirmResult:
    code: ConfirmResultCode


def begin_session(
    cursor: Cursor,
    *,
    tg_id: int,
    private_chat_id: int,
    now: datetime,
    inactivity_ttl: timedelta,
) -> None:
    inactivity_expires_at = now + inactivity_ttl
    cursor.execute(
        """
        INSERT INTO public.attendance_registration_sessions (
            tg_id, private_chat_id, stage,
            english_name, employee_id, preview_token_hash,
            created_at, last_activity_at, inactivity_expires_at,
            absolute_expires_at, preview_expires_at
        ) VALUES (
            %s, %s, 'awaiting_input',
            NULL, NULL, NULL,
            %s, %s, %s, %s, NULL
        )
        ON CONFLICT (tg_id) DO UPDATE SET
            private_chat_id = EXCLUDED.private_chat_id,
            stage = 'awaiting_input',
            english_name = NULL,
            employee_id = NULL,
            preview_token_hash = NULL,
            created_at = EXCLUDED.created_at,
            last_activity_at = EXCLUDED.last_activity_at,
            inactivity_expires_at = EXCLUDED.inactivity_expires_at,
            absolute_expires_at = EXCLUDED.absolute_expires_at,
            preview_expires_at = NULL
        """,
        (
            int(tg_id),
            int(private_chat_id),
            now,
            now,
            inactivity_expires_at,
            inactivity_expires_at,
        ),
    )


def is_active(
    cursor: Cursor,
    *,
    tg_id: int,
    private_chat_id: int,
    now: datetime,
) -> bool:
    cursor.execute(
        """
        DELETE FROM public.attendance_registration_sessions
        WHERE tg_id = %s
          AND (
              private_chat_id <> %s
              OR inactivity_expires_at < %s
              OR absolute_expires_at < %s
              OR (preview_expires_at IS NOT NULL AND preview_expires_at < %s)
          )
        """,
        (int(tg_id), int(private_chat_id), now, now, now),
    )
    cursor.execute(
        """
        SELECT 1
        FROM public.attendance_registration_sessions
        WHERE tg_id = %s
          AND private_chat_id = %s
          AND inactivity_expires_at >= %s
          AND absolute_expires_at >= %s
          AND (preview_expires_at IS NULL OR preview_expires_at >= %s)
        """,
        (int(tg_id), int(private_chat_id), now, now, now),
    )
    return cursor.fetchone() is not None


def clear_session(cursor: Cursor, *, tg_id: int) -> None:
    cursor.execute(
        "DELETE FROM public.attendance_registration_sessions WHERE tg_id = %s",
        (int(tg_id),),
    )


def touch_invalid_input(
    cursor: Cursor,
    *,
    tg_id: int,
    private_chat_id: int,
    now: datetime,
    inactivity_ttl: timedelta,
) -> bool:
    cursor.execute(
        """
        UPDATE public.attendance_registration_sessions
        SET last_activity_at = %s,
            inactivity_expires_at = %s,
            absolute_expires_at = %s
        WHERE tg_id = %s
          AND private_chat_id = %s
          AND inactivity_expires_at >= %s
          AND absolute_expires_at >= %s
        """,
        (
            now,
            now + inactivity_ttl,
            now + inactivity_ttl,
            int(tg_id),
            int(private_chat_id),
            now,
            now,
        ),
    )
    return int(cursor.rowcount or 0) == 1


def save_preview(
    cursor: Cursor,
    *,
    tg_id: int,
    private_chat_id: int,
    english_name: str,
    employee_id: str,
    token: str,
    now: datetime,
    inactivity_ttl: timedelta,
) -> datetime | None:
    preview_expires_at = now + inactivity_ttl
    cursor.execute(
        """
        UPDATE public.attendance_registration_sessions
        SET stage = 'awaiting_confirmation',
            english_name = %s,
            employee_id = %s,
            preview_token_hash = %s,
            last_activity_at = %s,
            inactivity_expires_at = %s,
            absolute_expires_at = %s,
            preview_expires_at = %s
        WHERE tg_id = %s
          AND private_chat_id = %s
          AND inactivity_expires_at >= %s
          AND absolute_expires_at >= %s
        RETURNING preview_expires_at
        """,
        (
            english_name,
            employee_id,
            _token_hash(token),
            now,
            preview_expires_at,
            preview_expires_at,
            preview_expires_at,
            int(tg_id),
            int(private_chat_id),
            now,
            now,
        ),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_preview(
    cursor: Cursor,
    *,
    token: str,
    tg_id: int,
    private_chat_id: int,
    now: datetime,
) -> RegistrationSessionRow | None:
    cursor.execute(
        """
        SELECT tg_id, private_chat_id, stage,
               english_name, employee_id, created_at, last_activity_at,
               inactivity_expires_at, absolute_expires_at, preview_expires_at
        FROM public.attendance_registration_sessions
        WHERE preview_token_hash = %s
          AND tg_id = %s
          AND private_chat_id = %s
          AND stage = 'awaiting_confirmation'
          AND inactivity_expires_at >= %s
          AND absolute_expires_at >= %s
          AND preview_expires_at >= %s
        """,
        (_token_hash(token), int(tg_id), int(private_chat_id), now, now, now),
    )
    row = cursor.fetchone()
    return RegistrationSessionRow(*row) if row else None


def cancel_preview(
    cursor: Cursor,
    *,
    token: str,
    tg_id: int,
    private_chat_id: int,
    now: datetime,
) -> bool:
    cursor.execute(
        """
        DELETE FROM public.attendance_registration_sessions
        WHERE preview_token_hash = %s
          AND tg_id = %s
          AND private_chat_id = %s
          AND stage = 'awaiting_confirmation'
          AND inactivity_expires_at >= %s
          AND absolute_expires_at >= %s
          AND preview_expires_at >= %s
        """,
        (_token_hash(token), int(tg_id), int(private_chat_id), now, now, now),
    )
    return int(cursor.rowcount or 0) == 1


def confirm_and_bind(
    cursor: Cursor,
    *,
    token: str,
    tg_id: int,
    private_chat_id: int,
    tg_username: str | None,
    now: datetime,
) -> ConfirmResult:
    cursor.execute(
        """
        SELECT tg_id, private_chat_id, english_name, employee_id,
               inactivity_expires_at, absolute_expires_at, preview_expires_at
        FROM public.attendance_registration_sessions
        WHERE preview_token_hash = %s
          AND stage = 'awaiting_confirmation'
        FOR UPDATE
        """,
        (_token_hash(token),),
    )
    session = cursor.fetchone()
    if session is None:
        return ConfirmResult(code="expired")

    (
        session_tg_id,
        session_chat_id,
        english_name,
        employee_id,
        inactivity_expires_at,
        absolute_expires_at,
        preview_expires_at,
    ) = session
    if int(session_tg_id) != int(tg_id) or int(session_chat_id) != int(private_chat_id):
        return ConfirmResult(code="owner_mismatch")
    if inactivity_expires_at < now or absolute_expires_at < now or preview_expires_at < now:
        _delete_session(cursor, tg_id=tg_id)
        return ConfirmResult(code="expired")

    if registrations_repo.get_by_tg_id_cur(cursor, tg_id=int(tg_id)) is not None:
        _delete_session(cursor, tg_id=tg_id)
        return ConfirmResult(code="tg_already_bound")

    existing = registrations_repo.get_by_employee_id_cur(
        cursor,
        employee_id=str(employee_id),
    )
    if existing is None:
        _delete_session(cursor, tg_id=tg_id)
        return ConfirmResult(code="employee_not_pre_registered")
    if existing.tg_id is not None:
        _delete_session(cursor, tg_id=tg_id)
        return ConfirmResult(code="employee_already_bound")
    if not _english_name_matches(existing.english_name, str(english_name)):
        _delete_session(cursor, tg_id=tg_id)
        return ConfirmResult(code="employee_name_mismatch")

    bound = registrations_repo.bind_tg_to_registration_cur(
        cursor,
        employee_id=str(employee_id),
        tg_id=int(tg_id),
        english_name=existing.english_name or str(english_name),
        registered_at_utc=now,
        registered_chat_id=int(private_chat_id),
        tg_username=tg_username,
    )
    if not bound:
        _delete_session(cursor, tg_id=tg_id)
        return ConfirmResult(code="employee_already_bound")
    _delete_session(cursor, tg_id=tg_id)
    return ConfirmResult(code="ok")


def _delete_session(cursor: Cursor, *, tg_id: int) -> None:
    cursor.execute(
        "DELETE FROM public.attendance_registration_sessions WHERE tg_id = %s",
        (int(tg_id),),
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _english_name_matches(expected: str | None, provided: str) -> bool:
    return bool(expected and expected.strip().casefold() == provided.strip().casefold())
