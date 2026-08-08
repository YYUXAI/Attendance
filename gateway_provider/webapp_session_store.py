from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from infra.db import get_cursor

from .webapp_session import GatewayWebAppPrincipal


_PROVIDER_SESSION_TTL = timedelta(hours=1)
_OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class ReplayedGatewayWebAppSessionError(ValueError):
    pass


class InvalidAttendanceWebAppSessionError(ValueError):
    pass


@dataclass(frozen=True)
class IssuedAttendanceWebAppSession:
    session_token: str
    expires_at: datetime


class AttendanceWebAppSessionStore:
    def __init__(
        self,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self._now = now
        self._token_factory = token_factory

    def exchange(
        self,
        principal: GatewayWebAppPrincipal,
    ) -> IssuedAttendanceWebAppSession:
        now = self._now().astimezone(UTC)
        token = self._token_factory()
        if _OPAQUE_TOKEN_RE.fullmatch(token) is None:
            raise ValueError("Attendance WebApp session token factory returned invalid data")
        expires_at = now + _PROVIDER_SESSION_TTL
        with get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.attendance_webapp_sessions (
                    session_token_hash,
                    gateway_session_id,
                    telegram_user_id,
                    created_at,
                    expires_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (gateway_session_id) DO NOTHING
                RETURNING gateway_session_id
                """,
                (
                    _token_hash(token),
                    principal.session_id,
                    principal.telegram_user_id,
                    now,
                    expires_at,
                ),
            )
            if cursor.fetchone() is None:
                raise ReplayedGatewayWebAppSessionError(
                    "Gateway WebApp exchange session was already consumed"
                )
        return IssuedAttendanceWebAppSession(
            session_token=token,
            expires_at=expires_at,
        )

    def authenticate(self, token: str) -> int:
        raw = token.strip()
        if _OPAQUE_TOKEN_RE.fullmatch(raw) is None:
            raise InvalidAttendanceWebAppSessionError(
                "Attendance WebApp session token is invalid"
            )
        now = self._now().astimezone(UTC)
        with get_cursor() as cursor:
            cursor.execute(
                """
                SELECT telegram_user_id
                FROM public.attendance_webapp_sessions
                WHERE session_token_hash = %s
                  AND expires_at > %s
                """,
                (_token_hash(raw), now),
            )
            row = cursor.fetchone()
        if row is None:
            raise InvalidAttendanceWebAppSessionError(
                "Attendance WebApp session token is invalid"
            )
        return int(row[0])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
