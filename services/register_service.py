from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from domain.registration.rules import parse_register_input
from domain.shared.result import ServiceResult
from repositories import registration_sessions_repo


@dataclass(frozen=True)
class RegisterPreview:
    token: str
    tg_id: int
    private_chat_id: int
    english_name: str
    employee_id: str
    expires_at: datetime


_REGISTER_SESSION_TTL = timedelta(minutes=15)


def mark_waiting_register_input(
    *,
    bot_owner: str,
    tg_id: int,
    private_chat_id: int,
    now: datetime | None = None,
) -> None:
    resolved_now = _resolved_now(now)
    registration_sessions_repo.begin_session(
        bot_owner=bot_owner,
        tg_id=tg_id,
        private_chat_id=private_chat_id,
        now=resolved_now,
        inactivity_ttl=_REGISTER_SESSION_TTL,
    )


def is_waiting_register_input(
    *,
    bot_owner: str,
    tg_id: int,
    private_chat_id: int,
    now: datetime | None = None,
) -> bool:
    return registration_sessions_repo.is_active(
        bot_owner=bot_owner,
        tg_id=tg_id,
        private_chat_id=private_chat_id,
        now=_resolved_now(now),
    )


def clear_waiting_register_input(*, bot_owner: str, tg_id: int) -> None:
    registration_sessions_repo.clear_session(bot_owner=bot_owner, tg_id=tg_id)


def preview_register(
    *,
    bot_owner: str,
    tg_id: int,
    private_chat_id: int,
    text: str,
    now: datetime | None = None,
) -> ServiceResult | RegisterPreview:
    resolved_now = _resolved_now(now)
    parsed = parse_register_input(text)
    if not parsed:
        registration_sessions_repo.touch_invalid_input(
            bot_owner=bot_owner,
            tg_id=tg_id,
            private_chat_id=private_chat_id,
            now=resolved_now,
            inactivity_ttl=_REGISTER_SESSION_TTL,
        )
        return ServiceResult(
            ok=False,
            message=(
                "格式不正确，请只发送一行：英文名$工号\n"
                "例如：GRANDFOR$74808\n"
                "（勿复制「请输入」「示例」等提示文字）"
            ),
            error_code="INVALID_FORMAT",
        )

    english_name, employee_id = parsed
    token = secrets.token_urlsafe(16)
    expires_at = registration_sessions_repo.save_preview(
        bot_owner=bot_owner,
        tg_id=tg_id,
        private_chat_id=private_chat_id,
        english_name=english_name,
        employee_id=employee_id,
        token=token,
        now=resolved_now,
        inactivity_ttl=_REGISTER_SESSION_TTL,
    )
    if expires_at is None:
        return ServiceResult(
            ok=False,
            message="注册会话已超时，请重新点击【注册】。",
            error_code="SESSION_EXPIRED",
        )
    return RegisterPreview(
        token=token,
        tg_id=tg_id,
        private_chat_id=private_chat_id,
        english_name=english_name,
        employee_id=employee_id,
        expires_at=expires_at,
    )


def cancel_preview(
    *,
    bot_owner: str,
    token: str,
    tg_id: int,
    private_chat_id: int,
    now: datetime | None = None,
) -> ServiceResult:
    cancelled = registration_sessions_repo.cancel_preview(
        bot_owner=bot_owner,
        token=token,
        tg_id=tg_id,
        private_chat_id=private_chat_id,
        now=_resolved_now(now),
    )
    if not cancelled:
        return ServiceResult(
            ok=False,
            message="取消已失效，请重新点击【注册】。",
            error_code="EXPIRED",
        )
    return ServiceResult(ok=True, message="已取消")


def confirm_register(
    *,
    bot_owner: str,
    token: str,
    tg_id: int,
    registered_chat_id: int,
    tg_username: str | None,
    now: datetime | None = None,
) -> ServiceResult:
    result = registration_sessions_repo.confirm_and_bind(
        bot_owner=bot_owner,
        token=token,
        tg_id=tg_id,
        private_chat_id=registered_chat_id,
        tg_username=tg_username,
        now=_resolved_now(now),
    )
    if result.code == "ok":
        return ServiceResult(ok=True, message="您成功注册")
    if result.code == "owner_mismatch":
        return ServiceResult(
            ok=False,
            message="该确认不属于当前账户，请重新点击【注册】。",
            error_code="TOKEN_OWNER_MISMATCH",
        )
    if result.code == "tg_already_bound":
        return ServiceResult(
            ok=False,
            message="该 Telegram 账户已绑定其他员工，请联系管理员处理",
            error_code="TG_ALREADY_BOUND",
        )
    if result.code == "employee_not_pre_registered":
        return ServiceResult(
            ok=False,
            message="该工号尚未预登记，请联系管理员处理",
            error_code="EMPLOYEE_NOT_PRE_REGISTERED",
        )
    if result.code == "employee_already_bound":
        return ServiceResult(
            ok=False,
            message="该工号已绑定其他 Telegram 账户，请联系管理员处理",
            error_code="EMPLOYEE_ALREADY_BOUND",
        )
    if result.code == "employee_name_mismatch":
        return ServiceResult(
            ok=False,
            message="英文名与工号资料不匹配，请确认或联系管理员",
            error_code="EMPLOYEE_NAME_MISMATCH",
        )
    return ServiceResult(
        ok=False,
        message="确认已失效，请重新点击【注册】。",
        error_code="EXPIRED",
    )


def get_preview(
    *,
    bot_owner: str,
    token: str,
    tg_id: int,
    private_chat_id: int,
    now: datetime | None = None,
) -> RegisterPreview | None:
    row = registration_sessions_repo.get_preview(
        bot_owner=bot_owner,
        token=token,
        tg_id=tg_id,
        private_chat_id=private_chat_id,
        now=_resolved_now(now),
    )
    if row is None or row.english_name is None or row.employee_id is None:
        return None
    return RegisterPreview(
        token=token,
        tg_id=row.tg_id,
        private_chat_id=row.private_chat_id,
        english_name=row.english_name,
        employee_id=row.employee_id,
        expires_at=row.preview_expires_at or row.inactivity_expires_at,
    )


def _resolved_now(value: datetime | None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def english_name_matches(expected: str | None, provided: str) -> bool:
    return bool(expected and expected.strip().casefold() == provided.strip().casefold())
