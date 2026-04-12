from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from domain.registration.rules import parse_register_input
from domain.shared.result import ServiceResult
from repositories import registrations_repo


@dataclass(frozen=True)
class RegisterPreview:
    token: str
    english_name: str
    employee_id: str


_pending: Dict[str, RegisterPreview] = {}
_waiting_input: Dict[int, bool] = {}


def mark_waiting_register_input(*, tg_id: int) -> None:
    _waiting_input[tg_id] = True


def is_waiting_register_input(*, tg_id: int) -> bool:
    return _waiting_input.get(tg_id, False)


def clear_waiting_register_input(*, tg_id: int) -> None:
    _waiting_input.pop(tg_id, None)


def preview_register(*, tg_id: int, text: str) -> ServiceResult | RegisterPreview:
    parsed = parse_register_input(text)
    if not parsed:
        return ServiceResult(
            ok=False,
            message="格式不正确，请输入：英文名$工号\n示例：Jeffery$72694",
            error_code="INVALID_FORMAT",
        )

    english_name, employee_id = parsed
    token = secrets.token_urlsafe(16)
    preview = RegisterPreview(token=token, english_name=english_name, employee_id=employee_id)
    _pending[token] = preview
    return preview


def cancel_preview(*, token: str, tg_id: int) -> None:
    _pending.pop(token, None)
    clear_waiting_register_input(tg_id=tg_id)


def confirm_register(
    *,
    token: str,
    tg_id: int,
    registered_chat_id: int,
    tg_username: str | None,
) -> ServiceResult:
    preview = _pending.get(token)
    if not preview:
        return ServiceResult(ok=False, message="确认已失效，请重新点击【注册】。", error_code="EXPIRED")

    if registrations_repo.get_by_tg_id(tg_id):
        return ServiceResult(
            ok=False,
            message="该 Telegram 账户已绑定其他员工，请联系管理员处理",
            error_code="TG_ALREADY_BOUND",
        )

    if registrations_repo.get_by_employee_id(preview.employee_id):
        return ServiceResult(
            ok=False,
            message="该工号已绑定其他 Telegram 账户，请联系管理员处理",
            error_code="EMPLOYEE_ALREADY_BOUND",
        )

    registrations_repo.insert_registration(
        employee_id=preview.employee_id,
        tg_id=tg_id,
        english_name=preview.english_name,
        registered_at_utc=datetime.now(timezone.utc),
        registered_chat_id=registered_chat_id,
        tg_username=tg_username,
    )

    _pending.pop(token, None)
    clear_waiting_register_input(tg_id=tg_id)
    return ServiceResult(ok=True, message="您成功注册")


def get_preview(*, token: str) -> Optional[RegisterPreview]:
    return _pending.get(token)
