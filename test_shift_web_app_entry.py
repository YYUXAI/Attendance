from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
from aiohttp.test_utils import TestClient, TestServer

from shift_web_app import create_shift_web_app


_SESSION_SECRET = "attendance-webapp-session-test-secret-0001"


def _database_url() -> str:
    value = (os.getenv("ATTENDANCE_TEST_DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("ATTENDANCE_TEST_DATABASE_URL is required")
    return value


def _apply_migration() -> None:
    root = Path(__file__).resolve().parent
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute((root / "migrations/0003_gateway_provider.sql").read_text())
            cursor.execute((root / "migrations/0004_registration_provider.sql").read_text())
            cursor.execute((root / "migrations/0005_webapp_sessions.sql").read_text())
            cursor.execute(
                "DELETE FROM attendance_webapp_sessions WHERE telegram_user_id IN (%s, %s)",
                (82001, 82002),
            )
            cursor.execute(
                "DELETE FROM admin_list WHERE admin_employee_id = %s",
                ("74808",),
            )
            cursor.execute(
                "DELETE FROM registrations WHERE employee_id = %s OR tg_id IN (%s, %s)",
                ("74808", 82001, 82002),
            )


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _gateway_session(
    *,
    tg_id: int,
    audience: str = "ATTENDANCE",
    issued_at: int | None = None,
    expires_at: int | None = None,
) -> str:
    now = int(time.time())
    iat = issued_at if issued_at is not None else now - 1
    exp = expires_at if expires_at is not None else iat + 120
    header = _base64url(
        json.dumps(
            {"alg": "HS256", "typ": "JWT"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    payload = _base64url(
        json.dumps(
            {
                "issuer": "UXAssistant-Gateway",
                "purpose": "PROVIDER_SESSION_EXCHANGE",
                "audience": audience,
                "subject": f"telegram-user:{tg_id}",
                "sessionId": f"session-{tg_id}-{iat}",
                "issuedAt": datetime.fromtimestamp(iat, UTC).isoformat().replace(
                    "+00:00", "Z"
                ),
                "expiresAt": datetime.fromtimestamp(exp, UTC).isoformat().replace(
                    "+00:00", "Z"
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    signing_input = f"{header}.{payload}"
    signature = _base64url(
        hmac.new(
            _SESSION_SECRET.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return f"{signing_input}.{signature}"


async def _get_shift_config(*, token: str) -> tuple[int, dict[str, object]]:
    app = create_shift_web_app(
        database_url=_database_url(),
        gateway_session_signing_secret=_SESSION_SECRET,
    )
    async with TestClient(TestServer(app)) as client:
        exchange = await client.post(
            "/api/v1/webapp/session/exchange",
            headers={"Authorization": f"Bearer {token}"},
        )
        exchange_payload = await exchange.json()
        if exchange.status != 200:
            return exchange.status, exchange_payload
        response = await client.get(
            "/api/v1/shift-config?year_month=2026-08",
            headers={
                "Authorization": f"Bearer {exchange_payload['sessionToken']}"
            },
        )
        return response.status, await response.json()


def test_shift_web_entry_exposes_only_current_business_routes() -> None:
    app = create_shift_web_app(
        database_url=_database_url(),
        gateway_session_signing_secret=_SESSION_SECRET,
    )
    paths = {resource.canonical for resource in app.router.resources()}

    assert "/healthz" in paths
    assert "/shift-app/" in paths
    assert "/api/v1/shift-config" in paths
    assert "/api/v1/webapp/session/exchange" in paths
    assert "/api/v1/shift-config/exchange-session" not in paths
    assert "/api/v1/shift-config/send-template" not in paths
    assert "/api/v1/shift-config/send-export" not in paths
    assert not any("checkin-app" in path for path in paths)
    assert not any("daily-attendance-report" in path for path in paths)


def test_gateway_session_allows_attendance_admin() -> None:
    _apply_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 82001, 82001),
            )
            cursor.execute(
                "INSERT INTO admin_list (admin_employee_id) VALUES (%s)",
                ("74808",),
            )

    status, payload = asyncio.run(
        _get_shift_config(token=_gateway_session(tg_id=82001))
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["year_month"] == "2026-08"


def test_gateway_session_does_not_grant_non_admin_access() -> None:
    _apply_migration()

    status, payload = asyncio.run(
        _get_shift_config(token=_gateway_session(tg_id=82002))
    )

    assert status == 403
    assert payload == {"ok": False, "code": "FORBIDDEN", "message": "无权限操作"}


def test_expired_or_wrong_audience_gateway_session_is_rejected() -> None:
    _apply_migration()
    now = int(time.time())

    expired_status, expired_payload = asyncio.run(
        _get_shift_config(
            token=_gateway_session(
                tg_id=82001,
                issued_at=now - 400,
                expires_at=now - 100,
            )
        )
    )
    audience_status, audience_payload = asyncio.run(
        _get_shift_config(
            token=_gateway_session(tg_id=82001, audience="OMNIAI2")
        )
    )

    assert expired_status == 401
    assert expired_payload["code"] == "SESSION_INVALID"
    assert audience_status == 401
    assert audience_payload["code"] == "SESSION_INVALID"


def test_malformed_gateway_session_is_rejected_without_server_error() -> None:
    _apply_migration()

    status, payload = asyncio.run(_get_shift_config(token="☃.invalid.session"))

    assert status == 401
    assert payload["code"] == "SESSION_INVALID"
