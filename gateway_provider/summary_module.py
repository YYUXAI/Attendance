from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from infra.db import database_url_scope
from repositories.profile_repo import get_registration_profile_by_tg_id


class AttendanceSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocolVersion: Literal["1.0"]
    registrationStatus: Literal[
        "UNREGISTERED",
        "PENDING",
        "APPROVED",
        "REJECTED",
    ]
    organizationDepartmentName: str | None
    profileBindingStatus: Literal["BOUND", "UNBOUND"]


def read_attendance_summary(
    *,
    database_url: str,
    telegram_user_id: int,
) -> AttendanceSummaryResponse:
    with database_url_scope(database_url):
        profile = get_registration_profile_by_tg_id(tg_id=telegram_user_id)
    if profile is None:
        return AttendanceSummaryResponse(
            protocolVersion="1.0",
            registrationStatus="UNREGISTERED",
            organizationDepartmentName=None,
            profileBindingStatus="UNBOUND",
        )
    return AttendanceSummaryResponse(
        protocolVersion="1.0",
        registrationStatus="APPROVED",
        organizationDepartmentName=profile.department_name,
        profileBindingStatus="BOUND",
    )
