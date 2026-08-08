from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
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


def _apply_current_migrations() -> None:
    root = Path(__file__).resolve().parent
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute((root / "migrations/0003_gateway_provider.sql").read_text())
            cursor.execute((root / "migrations/0004_registration_provider.sql").read_text())
            cursor.execute((root / "migrations/0005_webapp_sessions.sql").read_text())
            cursor.execute(
                "DELETE FROM attendance_webapp_sessions WHERE telegram_user_id IN (%s, %s)",
                (82501, 82502),
            )
            cursor.execute(
                "DELETE FROM admin_list WHERE admin_employee_id = %s",
                ("75808",),
            )
            cursor.execute(
                "DELETE FROM registrations WHERE employee_id = %s OR tg_id = %s",
                ("75808", 82501),
            )
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("75808", "SESSIONTEST", 82501, 82501),
            )
            cursor.execute(
                "INSERT INTO admin_list (admin_employee_id) VALUES (%s)",
                ("75808",),
            )


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _gateway_exchange_token(
    *,
    tg_id: int,
    session_id: str,
    now: datetime,
    audience: str = "ATTENDANCE",
    purpose: str = "PROVIDER_SESSION_EXCHANGE",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
    issued = issued_at or now - timedelta(seconds=1)
    expires = expires_at or issued + timedelta(seconds=120)
    header = _base64url(
        json.dumps(
            {"alg": "HS256", "typ": "JWT"},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    payload = _base64url(
        json.dumps(
            {
                "issuer": "UXAssistant-Gateway",
                "purpose": purpose,
                "audience": audience,
                "subject": f"telegram-user:{tg_id}",
                "sessionId": session_id,
                "issuedAt": issued.isoformat().replace("+00:00", "Z"),
                "expiresAt": expires.isoformat().replace("+00:00", "Z"),
            },
            separators=(",", ":"),
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


async def _exercise_exchange() -> tuple[int, dict[str, object], int, dict[str, object]]:
    app = create_shift_web_app(
        database_url=_database_url(),
        gateway_session_signing_secret=_SESSION_SECRET,
    )
    async with TestClient(TestServer(app)) as client:
        gateway_token = _gateway_exchange_token(
            tg_id=82501,
            session_id="wss.attendance-public-test-0001",
            now=datetime.now(UTC),
        )
        exchange = await client.post(
            "/api/v1/webapp/session/exchange",
            headers={"Authorization": f"Bearer {gateway_token}"},
        )
        exchange_payload = await exchange.json()
        provider_token = exchange_payload.get("sessionToken", "")
        business = await client.get(
            "/api/v1/shift-config?year_month=2026-08",
            headers={"Authorization": f"Bearer {provider_token}"},
        )
        return (
            exchange.status,
            exchange_payload,
            business.status,
            await business.json(),
        )


def test_gateway_exchange_token_becomes_provider_owned_session() -> None:
    _apply_current_migrations()

    exchange_status, exchange_payload, business_status, business_payload = (
        asyncio.run(_exercise_exchange())
    )

    assert exchange_status == 200
    assert exchange_payload["tokenType"] == "Bearer"
    assert exchange_payload["sessionToken"]
    assert business_status == 200
    assert business_payload["ok"] is True


async def _exercise_failure_contracts() -> dict[str, object]:
    app = create_shift_web_app(
        database_url=_database_url(),
        gateway_session_signing_secret=_SESSION_SECRET,
    )
    now = datetime.now(UTC)
    async with TestClient(TestServer(app)) as client:
        gateway_token = _gateway_exchange_token(
            tg_id=82501,
            session_id="wss.attendance-atomic-test-0002",
            now=now,
        )
        concurrent = await asyncio.gather(
            client.post(
                "/api/v1/webapp/session/exchange",
                headers={"Authorization": f"Bearer {gateway_token}"},
            ),
            client.post(
                "/api/v1/webapp/session/exchange",
                headers={"Authorization": f"Bearer {gateway_token}"},
            ),
        )
        concurrent_payloads = [await response.json() for response in concurrent]
        successful_payload = concurrent_payloads[
            [response.status for response in concurrent].index(200)
        ]
        provider_token = str(successful_payload["sessionToken"])

        direct = await client.get(
            "/api/v1/shift-config?year_month=2026-08",
            headers={"Authorization": f"Bearer {gateway_token}"},
        )
        wrong_audience = await client.post(
            "/api/v1/webapp/session/exchange",
            headers={
                "Authorization": "Bearer "
                + _gateway_exchange_token(
                    tg_id=82502,
                    session_id="wss.attendance-wrong-audience-0003",
                    now=now,
                    audience="OMNIAI2",
                )
            },
        )
        expired = await client.post(
            "/api/v1/webapp/session/exchange",
            headers={
                "Authorization": "Bearer "
                + _gateway_exchange_token(
                    tg_id=82502,
                    session_id="wss.attendance-expired-test-0004",
                    now=now,
                    issued_at=now - timedelta(seconds=121),
                    expires_at=now - timedelta(seconds=1),
                )
            },
        )
        tampered_token = _gateway_exchange_token(
            tg_id=82502,
            session_id="wss.attendance-tampered-test-0005",
            now=now,
        )
        tampered_token = tampered_token[:-1] + (
            "A" if tampered_token[-1] != "A" else "B"
        )
        tampered = await client.post(
            "/api/v1/webapp/session/exchange",
            headers={"Authorization": f"Bearer {tampered_token}"},
        )

        with psycopg2.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE attendance_webapp_sessions
                    SET expires_at = created_at + interval '1 microsecond'
                    WHERE gateway_session_id = %s
                    """,
                    ("wss.attendance-atomic-test-0002",),
                )
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM attendance_webapp_sessions
                    WHERE gateway_session_id = %s
                    """,
                    ("wss.attendance-atomic-test-0002",),
                )
                row_count = int(cursor.fetchone()[0])
        provider_expired = await client.get(
            "/api/v1/shift-config?year_month=2026-08",
            headers={"Authorization": f"Bearer {provider_token}"},
        )

        return {
            "concurrent_statuses": sorted(response.status for response in concurrent),
            "replay_code": next(
                payload["code"]
                for response, payload in zip(concurrent, concurrent_payloads)
                if response.status == 409
            ),
            "direct_status": direct.status,
            "wrong_audience_status": wrong_audience.status,
            "expired_status": expired.status,
            "tampered_status": tampered.status,
            "provider_expired_status": provider_expired.status,
            "row_count": row_count,
        }


def test_exchange_is_atomic_single_use_and_fails_closed() -> None:
    _apply_current_migrations()

    result = asyncio.run(_exercise_failure_contracts())

    assert result == {
        "concurrent_statuses": [200, 409],
        "replay_code": "SESSION_REPLAYED",
        "direct_status": 401,
        "wrong_audience_status": 401,
        "expired_status": 401,
        "tampered_status": 401,
        "provider_expired_status": 401,
        "row_count": 1,
    }
