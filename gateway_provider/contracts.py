from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)


StableId = Annotated[
    str,
    StringConstraints(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
    ),
]


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: int
    is_bot: bool
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: int
    type: Literal["private", "group", "supergroup", "channel"]
    title: str | None = None
    username: str | None = None


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)

    message_id: Annotated[int, Field(ge=0)]
    date: Annotated[int, Field(ge=0)]
    chat: TelegramChat
    sender: TelegramUser | None = Field(default=None, alias="from")
    text: str | None = None


class TelegramMessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    update_id: Annotated[int, Field(ge=0)]
    message: TelegramMessage


class GatewayEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    eventId: StableId
    target: Literal["ATTENDANCE"]
    routeReason: Literal["COMMAND"]
    conversationId: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    receivedAt: str
    telegramUpdate: TelegramMessageUpdate

    @field_validator("receivedAt")
    @classmethod
    def validate_received_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("receivedAt must be an ISO-8601 date-time") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("receivedAt must include a UTC offset")
        return value


class InlineKeyboardButton(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    callbackData: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class InlineKeyboardMarkup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    inlineKeyboard: Annotated[
        list[Annotated[list[InlineKeyboardButton], Field(min_length=1, max_length=8)]],
        Field(min_length=1, max_length=100),
    ]


class SendMessageAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["SEND_MESSAGE"]
    chatId: int
    text: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    replyToMessageId: Annotated[int, Field(ge=0)] | None = None
    replyMarkup: InlineKeyboardMarkup | None = None


class UnchangedSessionDirective(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    directive: Literal["UNCHANGED"]


class GatewayEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    eventId: StableId
    result: Literal["PROCESSED", "DUPLICATE"]
    session: UnchangedSessionDirective
    actions: Annotated[list[SendMessageAction], Field(max_length=100)]


def event_request_canonical_value(request: GatewayEventRequest) -> dict[str, object]:
    return request.model_dump(mode="json", by_alias=True, exclude_none=True)


def event_response_value(response: GatewayEventResponse) -> dict[str, object]:
    return response.model_dump(mode="json", by_alias=True, exclude_none=True)
