"""Fail-closed validation for process-specific Attendance runtime dependencies."""

from __future__ import annotations

from collections.abc import Mapping

from infra.attendance_group_policy import load_group_policies


_COMPONENTS = frozenset({"migrate", "provider", "webapp", "scheduler", "worker"})


def validate_attendance_process_environment(
    component: str,
    environment: Mapping[str, str],
) -> None:
    if component not in _COMPONENTS:
        raise RuntimeError("ATTENDANCE_RUNTIME_COMPONENT is invalid")
    _require(environment, "ATTENDANCE_DATABASE_URL")
    _fingerprint(environment, "ATTENDANCE_PUBLIC_CONFIG_FINGERPRINT")
    if component == "migrate":
        return
    if component in {"provider", "scheduler"}:
        load_group_policies(environment)
        _fingerprint(environment, "ATTENDANCE_GROUPS_FINGERPRINT")
        _validate_ai(environment)
    if component == "provider":
        _require(environment, "GATEWAY_TO_ATTENDANCE_BEARER_TOKEN")
        _require(environment, "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN")
        _require(environment, "GATEWAY_INTERNAL_BASE_URL")
    elif component == "webapp":
        _require(environment, "GATEWAY_WEBAPP_SESSION_SIGNING_SECRET")
    elif component == "scheduler":
        _require(environment, "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN")
        _require(environment, "GATEWAY_INTERNAL_BASE_URL")
        _validate_sheets(environment)
    elif component == "worker":
        _require(environment, "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN")
        _require(environment, "GATEWAY_INTERNAL_BASE_URL")


def _validate_ai(environment: Mapping[str, str]) -> None:
    enabled = _boolean(environment, "CHECKIN_AI_ENABLED")
    mode = _choice(environment, "CHECKIN_AI_MODE", {"assist", "required"})
    backend = _choice(
        environment,
        "CHECKIN_AI_EXTRACT_BACKEND",
        {"ollama", "ocr_only", "ocr_text_llm", "zhipu"},
    )
    if mode == "required" and not enabled:
        raise RuntimeError("CHECKIN_AI_MODE=required requires CHECKIN_AI_ENABLED=true")
    if mode == "required" and _boolean(
        environment, "CHECKIN_AI_CLOCK_FALLBACK_SEND_TIME"
    ):
        raise RuntimeError("required AI forbids message-time fallback")
    if not enabled:
        return
    if backend in {"zhipu", "ocr_text_llm"}:
        _require(environment, "CHECKIN_AI_API_KEY")
    if _boolean(environment, "CHECKIN_AI_PREMIUM_ENABLED"):
        _require(environment, "CHECKIN_AI_PREMIUM_API_KEY")


def _validate_sheets(environment: Mapping[str, str]) -> None:
    if not _boolean(environment, "GOOGLE_SHEETS_ENABLED"):
        return
    _require(environment, "GOOGLE_SHEETS_CREDENTIALS_JSON")
    _require(environment, "GOOGLE_SHEETS_SPREADSHEET_ID")
    if _boolean(environment, "REMOTE_DIFF_GOOGLE_SHEETS_ENABLED"):
        _require(environment, "REMOTE_DIFF_GOOGLE_SHEETS_SPREADSHEET_ID")
    if _boolean(environment, "TEST_GROUP_GOOGLE_SHEETS_ENABLED"):
        _require(environment, "TEST_GROUP_SHIFT_SPREADSHEET_ID")
        _require(environment, "TEST_GROUP_ATTENDANCE_SPREADSHEET_ID")
        _require(environment, "TEST_GROUP_ATTENDANCE_SHEET_TITLE")
    if _boolean(environment, "BBQ_GOOGLE_SHEETS_ENABLED"):
        _require(environment, "BBQ_GOOGLE_SHEETS_SPREADSHEET_ID")
        _require(environment, "BBQ_GOOGLE_SHEETS_SHEET_TITLE")


def _require(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value


def _boolean(environment: Mapping[str, str], name: str) -> bool:
    value = _require(environment, name).strip().lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return value == "true"


def _choice(environment: Mapping[str, str], name: str, values: set[str]) -> str:
    value = _require(environment, name).strip()
    if value not in values:
        raise RuntimeError(f"{name} is invalid")
    return value


def _fingerprint(environment: Mapping[str, str], name: str) -> str:
    value = _require(environment, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError(f"{name} is invalid")
    return value
