from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway_provider.contracts import GatewayAsyncActionRequest, SendMessageAction


def test_async_contract_requires_gateway_resolved_correlation_target() -> None:
    with pytest.raises(ValidationError):
        GatewayAsyncActionRequest.model_validate(
            {
                "protocolVersion": "1.0",
                "provider": "ATTENDANCE",
                "correlationId": "raw-target-bypass",
                "createdAt": "2026-08-11T10:00:00Z",
                "action": {
                    "actionId": "act.raw-target-bypass",
                    "type": "SEND_MESSAGE",
                    "chatId": 81001,
                    "text": "不得指定任意私聊目标",
                },
            },
            strict=True,
        )
    request = GatewayAsyncActionRequest.model_validate(
        {
            "protocolVersion": "1.0",
            "provider": "ATTENDANCE",
            "correlationId": "group-route-target",
            "createdAt": "2026-08-11T10:00:00Z",
            "action": {
                "actionId": "act.group-route-target",
                "type": "SEND_GROUP_MESSAGE",
                "routeKey": "group-route.attendance.0123456789abcdef0123456789abcdef01234567",
                "text": "群通知",
            },
        },
        strict=True,
    )
    assert request.action.type == "SEND_GROUP_MESSAGE"

    targeted = GatewayAsyncActionRequest.model_validate(
        {
            "protocolVersion": "1.0",
            "provider": "ATTENDANCE",
            "correlationId": "source-bound-target",
            "targetEventId": "telegram-update:installation:123",
            "createdAt": "2026-08-11T10:00:00Z",
            "action": {
                "actionId": "act.source-bound-target",
                "type": "SEND_MESSAGE",
                "chatId": -87001,
                "text": "source-bound",
            },
        },
        strict=True,
    )
    assert targeted.targetEventId == "telegram-update:installation:123"


@pytest.mark.parametrize(
    "reply_markup",
    [
        {"removeKeyboard": True},
        {
            "keyboard": [
                [{"text": "签到"}, {"text": "签退"}],
                [{"text": "离岗"}, {"text": "返岗"}],
            ],
            "resizeKeyboard": True,
            "isPersistent": True,
            "inputFieldPlaceholder": "选下方按钮或输入消息",
        },
    ],
)
def test_accepts_canonical_reply_keyboard_variants(reply_markup: dict[str, object]) -> None:
    action = SendMessageAction.model_validate(
        {
            "actionId": "act.reply-markup.001",
            "type": "SEND_MESSAGE",
            "chatId": 81001,
            "text": "菜单",
            "replyMarkup": reply_markup,
        },
        strict=True,
    )
    assert action.model_dump(exclude_none=True)["replyMarkup"] == reply_markup


def test_rejects_hybrid_reply_keyboard_variant() -> None:
    with pytest.raises(ValidationError):
        SendMessageAction.model_validate(
            {
                "actionId": "act.reply-markup.002",
                "type": "SEND_MESSAGE",
                "chatId": 81001,
                "text": "菜单",
                "replyMarkup": {
                    "removeKeyboard": True,
                    "keyboard": [[{"text": "签到"}]],
                },
            },
            strict=True,
        )


def test_accepts_only_an_exclusive_copy_text_inline_button() -> None:
    action = SendMessageAction.model_validate(
        {
            "actionId": "act.copy-text.001",
            "type": "SEND_MESSAGE",
            "chatId": -10081001,
            "text": "菜单",
            "replyMarkup": {
                "inlineKeyboard": [[
                    {"text": "复制", "copyText": "#打卡\n事项：签到"}
                ]]
            },
        },
        strict=True,
    )
    assert action.model_dump(exclude_none=True)["replyMarkup"] == {
        "inlineKeyboard": [[
            {"text": "复制", "copyText": "#打卡\n事项：签到"}
        ]]
    }

    with pytest.raises(ValidationError):
        SendMessageAction.model_validate(
            {
                "actionId": "act.copy-text.002",
                "type": "SEND_MESSAGE",
                "chatId": -10081001,
                "text": "菜单",
                "replyMarkup": {
                    "inlineKeyboard": [[{
                        "text": "复制",
                        "callbackData": "att:copy",
                        "copyText": "内容",
                    }]]
                },
            },
            strict=True,
        )


def test_accepts_only_an_exclusive_web_app_inline_button() -> None:
    action = SendMessageAction.model_validate(
        {
            "actionId": "act.web-app.001",
            "type": "SEND_MESSAGE",
            "chatId": 81001,
            "text": "菜单",
            "replyMarkup": {
                "inlineKeyboard": [[{
                    "text": "班表",
                    "webAppUrl": "https://attendance.example.test/shift-app/",
                }]]
            },
        },
        strict=True,
    )
    assert action.replyMarkup is not None
    with pytest.raises(ValidationError):
        SendMessageAction.model_validate(
            {
                "actionId": "act.web-app.mixed.001",
                "type": "SEND_MESSAGE",
                "chatId": 81001,
                "text": "菜单",
                "replyMarkup": {
                    "inlineKeyboard": [[{
                        "text": "班表",
                        "webAppUrl": "https://attendance.example.test/shift-app/",
                        "callbackData": "att:shift",
                    }]]
                },
            },
            strict=True,
        )


def test_accepts_the_old_markdown_parse_mode() -> None:
    action = SendMessageAction.model_validate(
        {
            "actionId": "act.markdown.001",
            "type": "SEND_MESSAGE",
            "chatId": 81001,
            "text": "*加粗*",
            "parseMode": "Markdown",
        },
        strict=True,
    )
    assert action.model_dump(exclude_none=True)["parseMode"] == "Markdown"
