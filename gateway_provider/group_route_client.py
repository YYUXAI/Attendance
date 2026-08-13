from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx


_ROUTE_REF_PATTERN = re.compile(
    r"^telegram-group-route\.[A-Za-z0-9._:-]{6,180}$"
)


class GatewayGroupRouteDirectoryUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class AttendanceGroupRoute:
    route_ref: str
    chat_id: int
    chat_type: str
    current_title: str
    public_username: str | None
    last_seen_at: str


@dataclass(frozen=True)
class GatewayAttendanceGroupRouteReader:
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

    def read(self) -> tuple[AttendanceGroupRoute, ...]:
        url = f"{self.base_url.rstrip('/')}/internal/v1/group-routes"
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=False,
            ) as client:
                response = client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.bearer_token}"},
                )
        except httpx.HTTPError as error:
            raise GatewayGroupRouteDirectoryUnavailableError() from error
        if response.status_code != 200:
            raise GatewayGroupRouteDirectoryUnavailableError()
        try:
            document = response.json()
            return _parse_attendance_routes(document)
        except (TypeError, ValueError, KeyError) as error:
            raise GatewayGroupRouteDirectoryUnavailableError() from error


def _parse_attendance_routes(document: object) -> tuple[AttendanceGroupRoute, ...]:
    if not isinstance(document, dict) or set(document) != {
        "protocolVersion",
        "provider",
        "routes",
    }:
        raise ValueError("invalid Gateway group route directory")
    if document["protocolVersion"] != "1.0" or document["provider"] != "ATTENDANCE":
        raise ValueError("invalid Gateway group route directory owner")
    raw_routes = document["routes"]
    if not isinstance(raw_routes, list):
        raise ValueError("invalid Gateway group routes")
    routes: list[AttendanceGroupRoute] = []
    chat_ids: set[int] = set()
    route_refs: set[str] = set()
    expected_keys = {
        "routeRef",
        "chatId",
        "chatType",
        "currentTitle",
        "publicUsername",
        "classification",
        "lastSeenAt",
    }
    for item in raw_routes:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ValueError("invalid Gateway group route")
        route_ref = item["routeRef"]
        chat_id = item["chatId"]
        chat_type = item["chatType"]
        title = item["currentTitle"]
        username = item["publicUsername"]
        last_seen_at = item["lastSeenAt"]
        if not isinstance(route_ref, str) or not _ROUTE_REF_PATTERN.fullmatch(route_ref):
            raise ValueError("invalid Gateway group route ref")
        if not isinstance(chat_id, int) or isinstance(chat_id, bool) or chat_id >= 0:
            raise ValueError("invalid Gateway group chat ID")
        if chat_type not in {"group", "supergroup"}:
            raise ValueError("invalid Gateway group chat type")
        if not isinstance(title, str) or not title or len(title) > 256:
            raise ValueError("invalid Gateway group title")
        if username is not None and (
            not isinstance(username, str) or not username or len(username) > 64
        ):
            raise ValueError("invalid Gateway group username")
        if item["classification"] != "ATTENDANCE":
            raise ValueError("Gateway returned a non-Attendance route")
        if not isinstance(last_seen_at, str):
            raise ValueError("invalid Gateway group observation timestamp")
        parsed_at = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
        if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
            raise ValueError("Gateway group observation timestamp lacks offset")
        if chat_id in chat_ids or route_ref in route_refs:
            raise ValueError("duplicate Gateway group route")
        chat_ids.add(chat_id)
        route_refs.add(route_ref)
        routes.append(
            AttendanceGroupRoute(
                route_ref=route_ref,
                chat_id=chat_id,
                chat_type=chat_type,
                current_title=title,
                public_username=username,
                last_seen_at=last_seen_at,
            )
        )
    return tuple(routes)


def _plain_http_host_allowed(hostname: str) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"} or "." not in hostname
