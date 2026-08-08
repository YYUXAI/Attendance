from __future__ import annotations

import os

from gateway_provider.app import (
    AttendanceGatewayProviderConfig,
    create_attendance_gateway_provider_app,
)


def _required_environment(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


app = create_attendance_gateway_provider_app(
    AttendanceGatewayProviderConfig(
        database_url=_required_environment("ATTENDANCE_DATABASE_URL"),
        gateway_to_attendance_bearer_token=_required_environment(
            "GATEWAY_TO_ATTENDANCE_BEARER_TOKEN"
        ),
        gateway_internal_base_url=_required_environment(
            "GATEWAY_INTERNAL_BASE_URL"
        ),
        attendance_to_gateway_bearer_token=_required_environment(
            "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN"
        ),
    )
)
