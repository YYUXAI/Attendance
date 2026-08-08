from __future__ import annotations

import hashlib
import json

import psycopg2
from psycopg2.extras import Json

from gateway_provider.contracts import (
    GatewayEventRequest,
    GatewayEventResponse,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    SendMessageAction,
    UnchangedSessionDirective,
    event_request_canonical_value,
    event_response_value,
)


class GatewayEventIdConflictError(RuntimeError):
    def __init__(self, event_id: str) -> None:
        super().__init__("Gateway event ID conflicts with a different request")
        self.event_id = event_id


class GatewayRouteOwnershipMismatchError(RuntimeError):
    pass


class AttendanceGatewayEventModule:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def process_event(self, request: GatewayEventRequest) -> GatewayEventResponse:
        request_hash = _request_hash(request)
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (request.eventId,),
                )
                cursor.execute(
                    """
                    SELECT request_hash, response_json
                    FROM gateway_processed_events
                    WHERE event_id = %s
                    """,
                    (request.eventId,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    stored_hash, stored_response = existing
                    if stored_hash != request_hash:
                        raise GatewayEventIdConflictError(request.eventId)
                    return GatewayEventResponse.model_validate(
                        {**stored_response, "result": "DUPLICATE"},
                        strict=True,
                    )

                response = _process_attendance_command(request)
                response_value = event_response_value(response)
                cursor.execute(
                    """
                    INSERT INTO gateway_processed_events (
                        event_id,
                        request_hash,
                        response_json,
                        processed_at
                    )
                    VALUES (%s, %s, %s, clock_timestamp())
                    """,
                    (request.eventId, request_hash, Json(response_value)),
                )
                return response


def _request_hash(request: GatewayEventRequest) -> str:
    canonical = json.dumps(
        event_request_canonical_value(request),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _process_attendance_command(request: GatewayEventRequest) -> GatewayEventResponse:
    message = request.telegramUpdate.message
    if message.chat.type != "private" or _command_name(message.text) != "/attendance":
        raise GatewayRouteOwnershipMismatchError()

    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            SendMessageAction(
                actionId=f"{request.eventId}.menu",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text="考勤功能",
                replyMarkup=InlineKeyboardMarkup(
                    inlineKeyboard=[
                        [
                            InlineKeyboardButton(
                                text="注册",
                                callbackData="att:register",
                            ),
                            InlineKeyboardButton(
                                text="个人",
                                callbackData="att:profile",
                            ),
                        ]
                    ]
                ),
            )
        ],
    )


def _command_name(text: str | None) -> str | None:
    if text is None:
        return None
    first_token = text.strip().split(maxsplit=1)[0]
    return first_token.split("@", maxsplit=1)[0].lower()
