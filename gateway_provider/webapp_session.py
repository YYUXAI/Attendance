from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_CLAIMS = frozenset(
    {
        "issuer",
        "purpose",
        "audience",
        "subject",
        "sessionId",
        "issuedAt",
        "expiresAt",
    }
)
_PURPOSE = "PROVIDER_SESSION_EXCHANGE"
_MAXIMUM_SESSION_SECONDS = 120
_MAXIMUM_CLOCK_SKEW_SECONDS = 30


class InvalidGatewayWebAppSessionError(ValueError):
    pass


@dataclass(frozen=True)
class GatewayWebAppPrincipal:
    telegram_user_id: int
    session_id: str
    expires_at: datetime


class GatewayWebAppSessionVerifier:
    def __init__(
        self,
        *,
        signing_secret: str,
        audience: str,
        issuer: str = "UXAssistant-Gateway",
    ) -> None:
        secret = signing_secret.strip()
        if len(secret) < 32:
            raise ValueError("Gateway WebApp session signing secret is too short")
        if audience not in {"ATTENDANCE", "OMNIAI2"}:
            raise ValueError("Gateway WebApp session audience is invalid")
        if not issuer.strip():
            raise ValueError("Gateway WebApp session issuer is required")
        self._secret = secret.encode("utf-8")
        self._audience = audience
        self._issuer = issuer

    def verify(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> GatewayWebAppPrincipal:
        raw = token.strip()
        if not raw or len(raw) > 4096:
            raise InvalidGatewayWebAppSessionError("session token is invalid")
        parts = raw.split(".")
        if len(parts) != 3:
            raise InvalidGatewayWebAppSessionError("session token is invalid")
        header_segment, payload_segment, supplied_signature = parts
        if any(_BASE64URL_RE.fullmatch(part) is None for part in parts):
            raise InvalidGatewayWebAppSessionError("session encoding is invalid")
        signing_input = f"{header_segment}.{payload_segment}"
        expected_signature = _base64url_encode(
            hmac.new(
                self._secret,
                signing_input.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise InvalidGatewayWebAppSessionError("session signature is invalid")

        header = _json_object(_base64url_decode(header_segment))
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise InvalidGatewayWebAppSessionError("session header is invalid")
        claims = _json_object(_base64url_decode(payload_segment))
        if frozenset(claims) != _CLAIMS:
            raise InvalidGatewayWebAppSessionError("session claims are invalid")
        if (
            claims["issuer"] != self._issuer
            or claims["purpose"] != _PURPOSE
            or claims["audience"] != self._audience
        ):
            raise InvalidGatewayWebAppSessionError("session scope is invalid")

        issued_at = _strict_timestamp(claims["issuedAt"])
        expires_at = _strict_timestamp(claims["expiresAt"])
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if issued_at > current + timedelta(seconds=_MAXIMUM_CLOCK_SKEW_SECONDS):
            raise InvalidGatewayWebAppSessionError("session is not active")
        if expires_at <= current or expires_at <= issued_at:
            raise InvalidGatewayWebAppSessionError("session is expired")
        if expires_at - issued_at > timedelta(seconds=_MAXIMUM_SESSION_SECONDS):
            raise InvalidGatewayWebAppSessionError("session lifetime is invalid")

        subject = claims["subject"]
        if not isinstance(subject, str) or not subject.startswith("telegram-user:"):
            raise InvalidGatewayWebAppSessionError("session subject is invalid")
        raw_user_id = subject.removeprefix("telegram-user:")
        if not raw_user_id.isdigit() or raw_user_id.startswith("0"):
            raise InvalidGatewayWebAppSessionError("session subject is invalid")
        telegram_user_id = int(raw_user_id)
        if telegram_user_id <= 0:
            raise InvalidGatewayWebAppSessionError("session subject is invalid")

        session_id = claims["sessionId"]
        if (
            not isinstance(session_id, str)
            or _SESSION_ID_RE.fullmatch(session_id) is None
        ):
            raise InvalidGatewayWebAppSessionError("session ID is invalid")
        return GatewayWebAppPrincipal(
            telegram_user_id=telegram_user_id,
            session_id=session_id,
            expires_at=expires_at,
        )


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    if not value or _BASE64URL_RE.fullmatch(value) is None:
        raise InvalidGatewayWebAppSessionError("session encoding is invalid")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except ValueError as error:
        raise InvalidGatewayWebAppSessionError(
            "session encoding is invalid"
        ) from error
    if _base64url_encode(decoded) != value:
        raise InvalidGatewayWebAppSessionError("session encoding is invalid")
    return decoded


def _json_object(value: bytes) -> dict[str, Any]:
    try:
        decoded = value.decode("utf-8", errors="strict")
        parsed = json.loads(decoded, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidGatewayWebAppSessionError("session JSON is invalid") from error
    if not isinstance(parsed, dict):
        raise InvalidGatewayWebAppSessionError("session JSON is invalid")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidGatewayWebAppSessionError("session JSON is invalid")
        result[key] = value
    return result


def _strict_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise InvalidGatewayWebAppSessionError("session timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidGatewayWebAppSessionError(
            "session timestamp is invalid"
        ) from error
    if parsed.tzinfo is None:
        raise InvalidGatewayWebAppSessionError("session timestamp is invalid")
    return parsed.astimezone(UTC)
