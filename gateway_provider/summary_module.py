from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from gateway_provider.contracts import InlineKeyboardButton
from infra.db import database_url_scope
from repositories.profile_repo import get_registration_profile_by_tg_id


class ShellPresentationLine(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order: Annotated[int, Field(ge=0, le=10_000)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class ShellPresentationActionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order: Annotated[int, Field(ge=0, le=10_000)]
    buttons: Annotated[list[InlineKeyboardButton], Field(min_length=1, max_length=8)]


class ProviderShellPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lines: Annotated[list[ShellPresentationLine], Field(min_length=2, max_length=10)]
    actionRows: Annotated[
        list[ShellPresentationActionRow],
        Field(min_length=1, max_length=10),
    ]


class AttendanceSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    shellPresentation: ProviderShellPresentation


def read_attendance_summary(
    *,
    database_url: str,
    telegram_user_id: int,
) -> AttendanceSummaryResponse:
    with database_url_scope(database_url):
        profile = get_registration_profile_by_tg_id(tg_id=telegram_user_id)
    if profile is None:
        return _attendance_summary(
            organization_label="未设置",
            profile_label="未绑定",
            include_registration=True,
        )
    return _attendance_summary(
        organization_label=(profile.department_name or "").strip() or "未设置",
        profile_label="已绑定",
        include_registration=False,
    )


def _attendance_summary(
    *,
    organization_label: str,
    profile_label: str,
    include_registration: bool,
) -> AttendanceSummaryResponse:
    action_rows = [
        ShellPresentationActionRow(
            order=100,
            buttons=[InlineKeyboardButton(text="考勤菜单", callbackData="att:menu")],
        )
    ]
    if include_registration:
        action_rows.append(
            ShellPresentationActionRow(
                order=300,
                buttons=[
                    InlineKeyboardButton(
                        text="绑定考勤资料",
                        callbackData="att:register",
                    )
                ],
            )
        )
    return AttendanceSummaryResponse(
        protocolVersion="1.0",
        shellPresentation=ProviderShellPresentation(
            lines=[
                ShellPresentationLine(
                    order=200,
                    text=f"组织归属：{organization_label}",
                ),
                ShellPresentationLine(order=300, text=f"考勤资料：{profile_label}"),
            ],
            actionRows=action_rows,
        ),
    )
