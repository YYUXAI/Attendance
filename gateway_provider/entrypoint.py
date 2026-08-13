from __future__ import annotations

import os

from gateway_provider.app import (
    AttendanceGatewayProviderConfig,
    create_attendance_gateway_provider_app,
)
from gateway_provider.runtime_security import assert_no_telegram_owner_credentials
from infra.runtime_config_validation import validate_attendance_process_environment


def _required_environment(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


assert_no_telegram_owner_credentials(os.environ)
validate_attendance_process_environment("provider", os.environ)


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
        shift_web_app_public_url=(
            os.environ.get("SHIFT_WEB_APP_PUBLIC_URL") or ""
        ).strip(),
        public_config_fingerprint=_required_environment(
            "ATTENDANCE_PUBLIC_CONFIG_FINGERPRINT"
        ),
    )
)
