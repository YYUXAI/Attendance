from __future__ import annotations

import pytest

from infra.runtime_config_validation import validate_attendance_process_environment


def _environment() -> dict[str, str]:
    return {
        "ATTENDANCE_DATABASE_URL": "postgresql://placeholder.invalid/attendance",
        "ATTENDANCE_GROUPS_JSON": "[]",
        "ATTENDANCE_GROUPS_FINGERPRINT": "a" * 64,
        "ATTENDANCE_PUBLIC_CONFIG_FINGERPRINT": "b" * 64,
        "GATEWAY_TO_ATTENDANCE_BEARER_TOKEN": "x" * 32,
        "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN": "y" * 32,
        "GATEWAY_INTERNAL_BASE_URL": "http://gateway-real:19081",
        "GATEWAY_WEBAPP_SESSION_SIGNING_SECRET": "z" * 32,
        "CHECKIN_AI_ENABLED": "true",
        "CHECKIN_AI_MODE": "required",
        "CHECKIN_AI_EXTRACT_BACKEND": "zhipu",
        "CHECKIN_AI_CLOCK_FALLBACK_SEND_TIME": "false",
        "CHECKIN_AI_PREMIUM_ENABLED": "false",
        "CHECKIN_AI_API_KEY": "fake-unit-test-key",
        "GOOGLE_SHEETS_ENABLED": "false",
    }


@pytest.mark.parametrize("component", ["migrate", "provider", "webapp", "scheduler", "worker"])
def test_each_runtime_component_accepts_only_its_required_dependencies(component: str) -> None:
    validate_attendance_process_environment(component, _environment())


def test_required_ai_key_and_message_time_fallback_fail_closed() -> None:
    missing_key = _environment()
    del missing_key["CHECKIN_AI_API_KEY"]
    with pytest.raises(RuntimeError, match="CHECKIN_AI_API_KEY is required"):
        validate_attendance_process_environment("provider", missing_key)

    fallback = _environment()
    fallback["CHECKIN_AI_CLOCK_FALLBACK_SEND_TIME"] = "true"
    with pytest.raises(RuntimeError, match="message-time fallback"):
        validate_attendance_process_environment("provider", fallback)

    placeholder = _environment()
    placeholder["CHECKIN_AI_API_KEY"] = "[UNBOUND]"
    with pytest.raises(RuntimeError, match="CHECKIN_AI_API_KEY is required"):
        validate_attendance_process_environment("provider", placeholder)


def test_disabled_ai_and_sheets_do_not_require_unrelated_private_bindings() -> None:
    environment = _environment()
    environment.update({"CHECKIN_AI_ENABLED": "false", "CHECKIN_AI_MODE": "assist"})
    del environment["CHECKIN_AI_API_KEY"]
    validate_attendance_process_environment("scheduler", environment)


def test_enabled_sheets_require_credentials_and_object_bindings() -> None:
    environment = _environment()
    environment["GOOGLE_SHEETS_ENABLED"] = "true"
    with pytest.raises(RuntimeError, match="GOOGLE_SHEETS_CREDENTIALS_JSON is required"):
        validate_attendance_process_environment("scheduler", environment)
    environment["GOOGLE_SHEETS_CREDENTIALS_JSON"] = '{"type":"service_account"}'
    with pytest.raises(RuntimeError, match="GOOGLE_SHEETS_SPREADSHEET_ID is required"):
        validate_attendance_process_environment("scheduler", environment)


def test_malformed_group_projection_fails_closed() -> None:
    environment = _environment()
    environment["ATTENDANCE_GROUPS_JSON"] = "not-json"
    with pytest.raises(RuntimeError, match="ATTENDANCE_GROUPS_JSON is invalid"):
        validate_attendance_process_environment("provider", environment)
