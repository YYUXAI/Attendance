from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
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
    caption: str | None = None
    photo: list[dict[str, object]] | None = None
    document: dict[str, object] | None = None


class TelegramMessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    update_id: Annotated[int, Field(ge=0)]
    message: TelegramMessage


class TelegramCallbackQuery(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)

    id: str
    sender: TelegramUser = Field(alias="from")
    message: TelegramMessage
    chat_instance: str
    data: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class TelegramCallbackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    update_id: Annotated[int, Field(ge=0)]
    callback_query: TelegramCallbackQuery


class TelegramInlineQuery(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)

    id: str
    sender: TelegramUser = Field(alias="from")
    query: str
    offset: str


class TelegramInlineQueryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    update_id: Annotated[int, Field(ge=0)]
    inline_query: TelegramInlineQuery


class TelegramFileReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    fileRef: StableId
    kind: Literal["PHOTO", "DOCUMENT"]
    fileName: Annotated[str, StringConstraints(min_length=1, max_length=255)] | None = None
    mimeType: Annotated[str, StringConstraints(min_length=3, max_length=128)] | None = None
    sizeBytes: Annotated[int, Field(ge=0, le=20 * 1024 * 1024)] | None = None


class GatewayEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    eventId: StableId
    target: Literal["ATTENDANCE"]
    routeReason: Literal[
        "COMMAND",
        "CALLBACK_NAMESPACE",
        "CONVERSATION_SESSION",
        "GROUP_OWNER",
        "INLINE_QUERY",
    ]
    conversationId: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    receivedAt: str
    telegramUpdate: (
        TelegramMessageUpdate | TelegramCallbackUpdate | TelegramInlineQueryUpdate
    )
    telegramFiles: Annotated[list[TelegramFileReference], Field(max_length=20)] = (
        Field(default_factory=list)
    )

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
    callbackData: Annotated[
        str,
        StringConstraints(min_length=1, max_length=64),
    ] | None = None
    switchInlineQueryCurrentChat: Annotated[
        str,
        StringConstraints(max_length=256),
    ] | None = None

    @model_validator(mode="after")
    def validate_exactly_one_action(self) -> "InlineKeyboardButton":
        values = (self.callbackData, self.switchInlineQueryCurrentChat)
        if sum(value is not None for value in values) != 1:
            raise ValueError("inline keyboard button requires exactly one action")
        return self


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


class AcquireSessionDirective(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    directive: Literal["ACQUIRE"]
    ttlSeconds: Annotated[int, Field(ge=1, le=86400)]


class ReleaseSessionDirective(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    directive: Literal["RELEASE"]


class AnswerCallbackAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["ANSWER_CALLBACK"]
    callbackQueryId: Annotated[str, StringConstraints(min_length=1)]


class AnswerInlineQueryAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["ANSWER_INLINE_QUERY"]
    inlineQueryId: Annotated[str, StringConstraints(min_length=1)]
    results: Annotated[list[dict[str, object]], Field(max_length=50)]
    cacheTimeSeconds: Annotated[int, Field(ge=0, le=86400)] | None = None
    isPersonal: bool | None = None


class GatewayEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    eventId: StableId
    result: Literal["PROCESSED", "DUPLICATE"]
    session: UnchangedSessionDirective | AcquireSessionDirective | ReleaseSessionDirective
    actions: Annotated[
        list[SendMessageAction | AnswerCallbackAction | AnswerInlineQueryAction],
        Field(max_length=100),
    ]


def event_request_canonical_value(request: GatewayEventRequest) -> dict[str, object]:
    return request.model_dump(mode="json", by_alias=True, exclude_none=True)


def event_response_value(response: GatewayEventResponse) -> dict[str, object]:
    return response.model_dump(mode="json", by_alias=True, exclude_none=True)
