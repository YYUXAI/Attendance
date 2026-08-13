from __future__ import annotations

import httpx
import pytest

from gateway_provider.group_route_client import (
    GatewayAttendanceGroupRouteReader,
    GatewayGroupRouteDirectoryUnavailableError,
)


def _directory(*routes: dict[str, object]) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "provider": "ATTENDANCE",
        "routes": list(routes),
    }


def _route(suffix: str, chat_id: int, chat_type: str) -> dict[str, object]:
    return {
        "routeRef": f"telegram-group-route.{suffix}",
        "chatId": chat_id,
        "chatType": chat_type,
        "currentTitle": suffix,
        "publicUsername": None,
        "classification": "ATTENDANCE",
        "lastSeenAt": "2026-08-13T10:00:00.000Z",
    }


def _response(payload: object) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_reads_zero_one_and_many_dynamic_attendance_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _directory(
        _route("attendance-a", -1001, "group"),
        _route("attendance-b", -1002, "supergroup"),
    )
    monkeypatch.setattr(httpx.Client, "get", lambda *_args, **_kwargs: _response(payload))
    reader = GatewayAttendanceGroupRouteReader(
        base_url="http://gateway",
        bearer_token="attendance-to-gateway-test-credential",
    )

    routes = reader.read()

    assert [(route.chat_id, route.route_ref) for route in routes] == [
        (-1001, "telegram-group-route.attendance-a"),
        (-1002, "telegram-group-route.attendance-b"),
    ]

    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda *_args, **_kwargs: _response(_directory()),
    )
    assert reader.read() == ()


@pytest.mark.parametrize(
    "payload",
    [
        {"protocolVersion": "1.0", "provider": "ATTENDANCE", "routes": "bad"},
        _directory({**_route("wrong-owner", -1001, "group"), "classification": "ORDINARY"}),
        _directory(_route("duplicate", -1001, "group"), _route("duplicate", -1002, "group")),
        _directory(_route("bad-chat", 1001, "group")),
    ],
)
def test_fails_closed_on_untrusted_or_ambiguous_route_directories(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(httpx.Client, "get", lambda *_args, **_kwargs: _response(payload))
    reader = GatewayAttendanceGroupRouteReader(
        base_url="http://gateway",
        bearer_token="attendance-to-gateway-test-credential",
    )

    with pytest.raises(GatewayGroupRouteDirectoryUnavailableError):
        reader.read()
