from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

GATEWAY_PROTOCOL_FINGERPRINT = (
    "sha256:1871b9f7c06ec77cf538f4be95b5a8aa0f1ab6f356873ddfdb355c607ae5c19d"
)


StableId = Annotated[
    str,
    StringConstraints(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
    ),
]

PositiveTelegramId = Annotated[
    str,
    StringConstraints(pattern=r"^[1-9][0-9]{0,18}$"),
]


class PrivateRegistrationSessionEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    telegramUserId: PositiveTelegramId
    privateChatId: PositiveTelegramId

    @model_validator(mode="after")
    def validate_private_actor(self) -> "PrivateRegistrationSessionEndRequest":
        telegram_user_id = int(self.telegramUserId)
        private_chat_id = int(self.privateChatId)
        if telegram_user_id > 2**63 - 1 or private_chat_id > 2**63 - 1:
            raise ValueError("Telegram actor IDs must fit int64")
        if telegram_user_id != private_chat_id:
            raise ValueError("privateChatId must identify the Telegram user")
        return self


class PrivateRegistrationSessionEndResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"] = "1.0"
    status: Literal["ENDED"] = "ENDED"


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


class TelegramEditedMessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    update_id: Annotated[int, Field(ge=0)]
    edited_message: TelegramMessage


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
    groupRouteRef: Annotated[
        str,
        StringConstraints(
            min_length=8,
            max_length=192,
            pattern=r"^telegram-group-route\.[A-Za-z0-9._:-]{6,180}$",
        ),
    ] | None = None
    groupClassification: Literal["ORDINARY", "ATTENDANCE", "REQUIREMENT"] | None = None
    messageThreadId: Annotated[int, Field(gt=0)] | None = None
    privateReachabilityRef: StableId | None = None
    telegramUpdate: (
        TelegramMessageUpdate
        | TelegramEditedMessageUpdate
        | TelegramCallbackUpdate
        | TelegramInlineQueryUpdate
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

    @model_validator(mode="after")
    def validate_group_route_ownership(self) -> "GatewayEventRequest":
        if self.routeReason == "GROUP_OWNER":
            if self.groupRouteRef is None or self.groupClassification != "ATTENDANCE":
                raise ValueError(
                    "Attendance group events require an ATTENDANCE dynamic group route"
                )
        elif self.groupRouteRef is not None or self.groupClassification is not None:
            raise ValueError("dynamic group route fields require GROUP_OWNER")
        return self

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
    copyText: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ] | None = None
    webAppUrl: AnyUrl | None = None

    @model_validator(mode="after")
    def validate_exactly_one_action(self) -> "InlineKeyboardButton":
        values = (
            self.callbackData,
            self.switchInlineQueryCurrentChat,
            self.copyText,
            self.webAppUrl,
        )
        if sum(value is not None for value in values) != 1:
            raise ValueError("inline keyboard button requires exactly one action")
        return self


class InlineKeyboardMarkup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    inlineKeyboard: Annotated[
        list[Annotated[list[InlineKeyboardButton], Field(min_length=1, max_length=8)]],
        Field(min_length=1, max_length=100),
    ]


class ReplyKeyboardButton(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class ReplyKeyboardMarkup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    keyboard: Annotated[
        list[Annotated[list[ReplyKeyboardButton], Field(min_length=1, max_length=8)]],
        Field(min_length=1, max_length=100),
    ]
    isPersistent: bool | None = None
    resizeKeyboard: bool | None = None
    oneTimeKeyboard: bool | None = None
    inputFieldPlaceholder: Annotated[
        str,
        StringConstraints(min_length=1, max_length=64),
    ] | None = None
    selective: bool | None = None


class ReplyKeyboardRemoveMarkup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    removeKeyboard: Literal[True]
    selective: bool | None = None


class SendMessageAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["SEND_MESSAGE"]
    chatId: int
    text: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    parseMode: Literal["HTML", "Markdown"] | None = None
    replyToMessageId: Annotated[int, Field(ge=0)] | None = None
    replyMarkup: (
        InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemoveMarkup | None
    ) = None


class SendGroupMessageAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["SEND_GROUP_MESSAGE"]
    routeKey: Annotated[
        str,
        StringConstraints(
            min_length=3,
            max_length=128,
            pattern=r"^[a-z0-9][a-z0-9._:-]+$",
        ),
    ]
    text: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    parseMode: Literal["HTML", "Markdown"] | None = None
    replyMarkup: (
        InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemoveMarkup | None
    ) = None


class BytesMediaSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: Literal["BYTES"]
    contentBase64: Annotated[str, StringConstraints(max_length=67_108_864)]
    fileName: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    mimeType: Annotated[str, StringConstraints(min_length=3, max_length=128)]

    @field_validator("contentBase64")
    @classmethod
    def validate_base64(cls, value: str) -> str:
        try:
            base64.b64decode(value, validate=True)
        except ValueError as error:
            raise ValueError("contentBase64 must be canonical base64") from error
        return value


class SendDocumentAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["SEND_DOCUMENT"]
    chatId: int
    document: BytesMediaSource
    caption: Annotated[str, StringConstraints(max_length=1024)] | None = None
    replyToMessageId: Annotated[int, Field(ge=0)] | None = None


class SendGroupDocumentAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["SEND_GROUP_DOCUMENT"]
    routeKey: Annotated[
        str,
        StringConstraints(
            min_length=3,
            max_length=128,
            pattern=r"^[a-z0-9][a-z0-9._:-]+$",
        ),
    ]
    document: BytesMediaSource
    caption: Annotated[str, StringConstraints(max_length=1024)] | None = None


class DeleteMessageAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actionId: StableId
    type: Literal["DELETE_MESSAGE"]
    chatId: int
    messageId: Annotated[int, Field(ge=0)] | None = None
    messageIdSourceActionId: StableId | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "DeleteMessageAction":
        if (self.messageId is None) == (self.messageIdSourceActionId is None):
            raise ValueError("delete message requires exactly one target")
        return self


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


class RegistrationFollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["REQUEST_OMNI_REGISTRATION"]
    businessUsername: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    employeeId: Annotated[str, StringConstraints(pattern=r"^[0-9]{3,8}$")]


class GatewayEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    eventId: StableId
    result: Literal["PROCESSED", "DUPLICATE"]
    session: UnchangedSessionDirective | AcquireSessionDirective | ReleaseSessionDirective
    actions: Annotated[
        list[
            SendMessageAction
            | SendDocumentAction
            | DeleteMessageAction
            | AnswerCallbackAction
            | AnswerInlineQueryAction
        ],
        Field(max_length=100),
    ]
    followUp: RegistrationFollowUp | None = None


class GatewayAsyncActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    provider: Literal["ATTENDANCE"]
    relatedEventId: StableId | None = None
    targetEventId: StableId | None = None
    correlationId: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=256,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
        ),
    ] | None = None
    createdAt: str
    action: (
        SendMessageAction
        | SendGroupMessageAction
        | SendDocumentAction
        | SendGroupDocumentAction
        | DeleteMessageAction
        | AnswerCallbackAction
        | AnswerInlineQueryAction
    )

    @field_validator("createdAt")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("createdAt must be an ISO-8601 date-time") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("createdAt must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_reference(self) -> "GatewayAsyncActionRequest":
        if (self.relatedEventId is None) == (self.correlationId is None):
            raise ValueError(
                "async action requires exactly one relatedEventId or correlationId"
            )
        if self.targetEventId is not None and self.correlationId is None:
            raise ValueError("targetEventId requires correlationId")
        if (
            self.correlationId is not None
            and self.targetEventId is None
            and not isinstance(
                self.action, (SendGroupMessageAction, SendGroupDocumentAction)
            )
        ):
            raise ValueError("correlation action target must be resolved by Gateway")
        if self.relatedEventId is not None and isinstance(
            self.action, (SendGroupMessageAction, SendGroupDocumentAction)
        ):
            raise ValueError("source-event action must use its event target")
        return self


class GatewayAsyncActionAcceptanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    actionId: StableId
    result: Literal["ACCEPTED", "DUPLICATE"]


class GatewayTelegramResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    accepted: Literal[True]
    messageId: Annotated[int, Field(ge=0)] | None = None
    fileId: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ] | None = None


class GatewayReceiptFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: Literal[
        "INVALID_ACTION",
        "FORBIDDEN",
        "NOT_FOUND",
        "RATE_LIMIT_EXHAUSTED",
        "TELEGRAM_ERROR",
        "NETWORK_UNKNOWN",
        "ACTION_EXPIRED",
        "PREDECESSOR_FAILED",
    ]
    terminal: Literal[True]


class GatewayDeliveryReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    receiptId: StableId
    provider: Literal["ATTENDANCE"]
    actionId: StableId
    relatedEventId: StableId | None = None
    correlationId: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=256,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
        ),
    ] | None = None
    status: Literal[
        "DELIVERED",
        "PERMANENTLY_FAILED",
        "UNCERTAIN",
        "SUPERSEDED",
    ]
    attemptedAt: str
    telegramResult: GatewayTelegramResult | None = None
    failure: GatewayReceiptFailure | None = None

    @field_validator("attemptedAt")
    @classmethod
    def validate_attempted_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("attemptedAt must be an ISO-8601 date-time") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("attemptedAt must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> "GatewayDeliveryReceiptRequest":
        if (self.relatedEventId is None) == (self.correlationId is None):
            raise ValueError(
                "receipt requires exactly one relatedEventId or correlationId"
            )
        if self.status == "DELIVERED":
            if self.telegramResult is None or self.failure is not None:
                raise ValueError("DELIVERED receipt requires only telegramResult")
            return self
        if self.failure is None or self.telegramResult is not None:
            raise ValueError("failed receipt requires only failure")
        if self.status == "UNCERTAIN" and self.failure.code != "NETWORK_UNKNOWN":
            raise ValueError("UNCERTAIN receipt requires NETWORK_UNKNOWN")
        if self.status == "SUPERSEDED" and self.failure.code not in {
            "ACTION_EXPIRED",
            "PREDECESSOR_FAILED",
        }:
            raise ValueError(
                "SUPERSEDED receipt requires ACTION_EXPIRED or PREDECESSOR_FAILED"
            )
        return self


def event_request_canonical_value(request: GatewayEventRequest) -> dict[str, object]:
    return request.model_dump(mode="json", by_alias=True, exclude_none=True)


def event_response_value(response: GatewayEventResponse) -> dict[str, object]:
    return response.model_dump(mode="json", by_alias=True, exclude_none=True)
