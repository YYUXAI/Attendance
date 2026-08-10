from __future__ import annotations

from datetime import datetime, timezone

from psycopg2.extensions import cursor as Cursor

from gateway_provider.contracts import (
    GatewayEventRequest,
    GatewayEventResponse,
    ReleaseSessionDirective,
    SendMessageAction,
    TelegramMessage,
    TelegramMessageUpdate,
)
from gateway_provider.export_module import is_admin


def is_admin_test_message(message: TelegramMessage) -> bool:
    return _is_standard_command(message.text, name="test") or _is_standard_command(
        message.caption,
        name="test",
    )


def process_admin_test_message(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if sender is None:
        return _response(request, message, text="")
    try:
        allowed = is_admin(cursor, tg_id=sender.id)
    except Exception:
        text = "暂时无法校验权限，请稍后再试。"
    else:
        if not allowed:
            text = "你没有权限使用该指令"
        else:
            now = datetime.fromisoformat(request.receivedAt.replace("Z", "+00:00"))
            now_utc = now.astimezone(timezone.utc)
            username = (sender.username or "").strip()
            lines = [
                f"telegram_id：{sender.id}",
                "",
                f"用户名：@{username}" if username else "用户名：无",
                f"chat_id：{message.chat.id}",
                f"utc_now：{now_utc.strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            attachment_file_id = _attachment_file_id(message)
            if attachment_file_id:
                lines.append(f"file_id：{attachment_file_id}")
            text = "\n".join(lines)
    return _response(request, message, text=text)


def _response(
    request: GatewayEventRequest,
    message: TelegramMessage,
    *,
    text: str,
) -> GatewayEventResponse:
    actions = [] if not text else [
        SendMessageAction(
            actionId=f"{request.eventId}.reply",
            type="SEND_MESSAGE",
            chatId=message.chat.id,
            replyToMessageId=message.message_id,
            text=text,
        )
    ]
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=ReleaseSessionDirective(directive="RELEASE"),
        actions=actions,
    )


def _attachment_file_id(message: TelegramMessage) -> str | None:
    if message.document is not None:
        value = message.document.get("file_id")
        return str(value) if value else None
    if message.photo:
        value = message.photo[-1].get("file_id")
        return str(value) if value else None
    return None


def _is_standard_command(value: str | None, *, name: str) -> bool:
    text = (value or "").strip()
    command = f"/{name}"
    return text == command or (
        text.startswith(f"{command}@")
        and " " not in text
        and len(text) > len(command) + 1
    )
