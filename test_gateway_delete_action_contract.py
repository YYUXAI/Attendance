from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway_provider.contracts import GatewayEventResponse


def _response_with_delete(delete: dict[str, object]) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-delete-contract",
        "result": "PROCESSED",
        "session": {"directive": "UNCHANGED"},
        "actions": [delete],
    }


def test_delete_message_accepts_exactly_one_explicit_or_action_result_target() -> None:
    by_action = GatewayEventResponse.model_validate(
        _response_with_delete({
            "actionId": "evt-attendance-delete-contract.delete",
            "type": "DELETE_MESSAGE",
            "chatId": 81002,
            "messageIdSourceActionId": "evt-attendance-delete-contract.progress",
        }),
        strict=True,
    )

    assert by_action.actions[0].model_dump(exclude_none=True) == {
        "actionId": "evt-attendance-delete-contract.delete",
        "type": "DELETE_MESSAGE",
        "chatId": 81002,
        "messageIdSourceActionId": "evt-attendance-delete-contract.progress",
    }
    with pytest.raises(ValidationError):
        GatewayEventResponse.model_validate(
            _response_with_delete({
                "actionId": "evt-attendance-delete-contract.delete",
                "type": "DELETE_MESSAGE",
                "chatId": 81002,
                "messageId": 502,
                "messageIdSourceActionId": "evt-attendance-delete-contract.progress",
            }),
            strict=True,
        )
