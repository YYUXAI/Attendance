from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx


MAXIMUM_FILE_BYTES = 20 * 1024 * 1024


class GatewayFileUnavailableError(RuntimeError):
    pass


class GatewayFileTooLargeError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayFileReader:
    base_url: str
    bearer_token: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("gateway_internal_base_url must be an HTTP(S) URL")
        if parsed.scheme == "http" and not _plain_http_host_allowed(parsed.hostname):
            raise ValueError(
                "plain HTTP Gateway transport is allowed only on loopback or internal hosts"
            )
        if len(self.bearer_token) < 32:
            raise ValueError(
                "attendance_to_gateway_bearer_token must contain at least 32 characters"
            )

    def read(self, *, file_ref: str, declared_size_bytes: int | None) -> bytes:
        if declared_size_bytes is not None and declared_size_bytes > MAXIMUM_FILE_BYTES:
            raise GatewayFileTooLargeError()
        url = (
            f"{self.base_url.rstrip('/')}"
            f"/internal/v1/telegram-files/{quote(file_ref, safe='')}"
        )
        try:
            with httpx.Client(
                timeout=httpx.Timeout(60.0, connect=5.0),
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "GET",
                    url,
                    headers={"Authorization": f"Bearer {self.bearer_token}"},
                ) as response:
                    if response.status_code == 413:
                        raise GatewayFileTooLargeError()
                    if response.status_code != 200:
                        raise GatewayFileUnavailableError()
                    length = _content_length(response.headers.get("content-length"))
                    if length is not None and length > MAXIMUM_FILE_BYTES:
                        raise GatewayFileTooLargeError()
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > MAXIMUM_FILE_BYTES:
                            raise GatewayFileTooLargeError()
                    data = bytes(payload)
                    _verify_digest(data, response.headers.get("digest"))
                    return data
        except (GatewayFileTooLargeError, GatewayFileUnavailableError):
            raise
        except httpx.HTTPError as error:
            raise GatewayFileUnavailableError() from error


def _plain_http_host_allowed(hostname: str) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"} or "." not in hostname


def _content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        raise GatewayFileUnavailableError() from error
    if parsed < 0:
        raise GatewayFileUnavailableError()
    return parsed


def _verify_digest(payload: bytes, value: str | None) -> None:
    if value is None or not value.startswith("sha-256="):
        raise GatewayFileUnavailableError()
    encoded = value.removeprefix("sha-256=")
    expected = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
    if not hmac.compare_digest(encoded, expected):
        raise GatewayFileUnavailableError()
