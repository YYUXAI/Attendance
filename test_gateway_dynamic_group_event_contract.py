from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway_provider.contracts import GatewayEventRequest


def test_accepts_only_attendance_classified_dynamic_group_events() -> None:
    parsed = GatewayEventRequest.model_validate(_group_event(), strict=True)

    assert parsed.groupRouteRef == "telegram-group-route.attendance-test"
    assert parsed.groupClassification == "ATTENDANCE"

    for invalid in (
        {**_group_event(), "groupRouteRef": None},
        {**_group_event(), "groupClassification": "ORDINARY"},
        {
            **_group_event(),
            "routeReason": "COMMAND",
            "groupRouteRef": "telegram-group-route.attendance-test",
        },
    ):
        with pytest.raises(ValidationError):
            GatewayEventRequest.model_validate(invalid, strict=True)


def _group_event() -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-dynamic-group-1",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "conversationId": "telegram:chat:-10081002",
        "receivedAt": "2026-08-13T10:00:00Z",
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
        "telegramUpdate": {
            "update_id": 1203,
            "message": {
                "message_id": 703,
                "date": 1786176120,
                "chat": {
                    "id": -10081002,
                    "type": "supergroup",
                    "title": "ux助手考勤测试群",
                },
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Group",
                },
                "text": "签到",
            },
        },
    }
