from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from infra.public_runtime_plan import (
    ROOT_DERIVED_ATTENDANCE_ENVIRONMENT,
    derive_attendance_public_runtime_plan,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "config" / "attendance-public-config.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def test_attendance_public_config_schema_accepts_complete_public_config() -> None:
    assert list(VALIDATOR.iter_errors(_fixture())) == []


def test_attendance_public_config_schema_rejects_unknown_and_missing_fields() -> None:
    unknown = _fixture()
    unknown["ai"]["privateValue"] = "forbidden"
    assert any(error.validator == "additionalProperties" for error in VALIDATOR.iter_errors(unknown))

    nested_unknown = _fixture()
    nested_unknown["sheets"]["profiles"]["remoteDiff"]["privateValue"] = "forbidden"
    assert any(
        error.validator == "unevaluatedProperties"
        for error in VALIDATOR.iter_errors(nested_unknown)
    )

    missing = _fixture()
    del missing["scheduler"]["dailySummaryTime"]
    assert any(error.validator == "required" for error in VALIDATOR.iter_errors(missing))


def test_attendance_public_config_has_only_logical_private_references() -> None:
    config = _fixture()
    rendered = json.dumps(config, ensure_ascii=False)
    assert "postgresql://" not in rendered
    assert "TELEGRAM_BOT_TOKEN" not in rendered
    assert "groupRef" not in rendered
    assert "routeKey" not in rendered
    assert config["credentials"]["gatewayToAttendanceBearerRef"] != (
        config["credentials"]["attendanceToGatewayBearerRef"]
    )
    assert config["webapp"]["signingSecretRef"] == "attendance_webapp_session_signing"
    assert config["sheets"]["objectBindingsIdentifierRef"] == "attendance_google_sheet_objects"


def test_attendance_runtime_plan_contains_only_public_env_and_file_mappings() -> None:
    plan = derive_attendance_public_runtime_plan(_fixture())
    assert plan.public_environment["SHIFT_WEB_PORT"] == "19084"
    assert "GATEWAY_ATTENDANCE_CHAT_IDS" not in plan.public_environment
    assert "GROUP_DAILY_SUMMARY_ROUTE_KEYS_JSON" not in plan.public_environment
    assert "DAILY_ATTENDANCE_REPORT_ROUTE_KEY" not in plan.public_environment
    assert "FORMAL_GROUP_ROSTER_SOURCE_MAP" not in plan.public_environment
    assert "ATTENDANCE_DATABASE_URL" not in plan.public_environment
    assert "GATEWAY_TO_ATTENDANCE_BEARER_TOKEN" not in plan.public_environment
    assert all(
        target.endswith("_FILE")
        for binding in plan.file_bindings
        for target in binding.target_file_variables
    )
    assert plan.derived_private_files[0]["bindingRef"] == "attendance_google_sheet_objects"
    rendered = repr(plan)
    assert "postgresql://" not in rendered


def test_attendance_runtime_plan_covers_every_non_database_legacy_binding() -> None:
    inventory = json.loads(
        (ROOT / "config" / "legacy-runtime-env-inventory.json").read_text(encoding="utf-8")
    )["categories"]
    plan = derive_attendance_public_runtime_plan(_fixture())
    public_targets = set(plan.public_environment)
    secret_targets = {
        target.removesuffix("_FILE")
        for binding in plan.file_bindings
        for target in binding.target_file_variables
    }
    identifier_targets = {
        target.removesuffix("_FILE")
        for derived in plan.derived_private_files
        for target in derived["targetFileVariables"]
        if target != "GROUP_DAILY_SUMMARY_ROUTE_KEYS_JSON_FILE"
    }

    assert set(inventory["public"]) <= public_targets
    assert set(inventory["sensitive_secret"]) <= secret_targets
    assert set(inventory["sensitive_identifier"]) <= identifier_targets
    assert set(inventory["derived_runtime_value"]) <= (
        public_targets | set(ROOT_DERIVED_ATTENDANCE_ENVIRONMENT)
    )
    assert not set(inventory["business_database_truth"]) & (public_targets | secret_targets | identifier_targets)


def _fixture() -> dict[str, object]:
    return deepcopy({
        "database": {
            "logicalName": "attendance_v1",
            "applicationRole": "ux_attendance_app",
            "connectionSecretRef": "attendance_database_url",
        },
        "provider": {
            "host": "0.0.0.0",
            "port": 19083,
            "internalServiceAlias": "attendance-provider",
        },
        "webapp": {
            "enabled": True,
            "publicBaseUrl": "https://ux-assistant-test.example.invalid",
            "host": "0.0.0.0",
            "port": 19084,
            "timezone": "Asia/Shanghai",
            "browserDev": False,
            "signingSecretRef": "attendance_webapp_session_signing",
        },
        "ai": {
            "enabled": True,
            "extractBackend": "zhipu",
            "apiBaseUrl": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4v-flash",
            "textModel": "glm-4v-flash",
            "mode": "required",
            "maxClockSkewMinutes": 30,
            "timeoutSeconds": 180,
            "trustSenderWhenNameUnreadable": False,
            "nameVerify": "vision",
            "clockFallbackSendTime": False,
            "ocr": {"engine": "tesseract", "easyOcrGpu": False, "maxConcurrent": 2},
            "apiKeySecretRef": "attendance_ai_api_key",
            "premium": {
                "enabled": True,
                "apiBaseUrl": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4.6v",
                "apiKeySecretRef": "attendance_premium_ai_api_key",
            },
        },
        "sheets": {
            "enabled": False,
            "syncIntervalSeconds": 14400,
            "timezone": "Asia/Shanghai",
            "yearMonth": "2026-08",
            "profiles": {
                "remoteDiff": {"enabled": False, "timezone": "Asia/Shanghai"},
                "testGroup": {
                    "enabled": False,
                    "timezone": "Asia/Shanghai",
                    "attendanceSheetTitle": "Attendance",
                    "slackCheckin": True,
                },
                "bbq": {
                    "enabled": False,
                    "timezone": "Asia/Shanghai",
                    "sheetTitle": "Attendance",
                },
            },
            "credentialsSecretRef": "attendance_google_service_account",
            "objectBindingsIdentifierRef": "attendance_google_sheet_objects",
        },
        "scheduler": {
            "enabled": True,
            "pollSeconds": 30,
            "leaseSeconds": 300,
            "timezone": "Asia/Shanghai",
            "dailySummaryTime": "23:30",
            "dailySummarySkipDate": "",
            "dailyReportEnabled": True,
            "dailyReportTime": "23:00",
            "sheetSyncIntervalSeconds": 14400,
        },
        "worker": {
            "enabled": True,
            "pollSeconds": 2,
            "leaseSeconds": 30,
            "batchSize": 20,
            "timeoutSeconds": 10,
            "maximumAcceptanceAttempts": 8,
        },
        "observability": {"logLevel": "INFO"},
        "credentials": {
            "gatewayToAttendanceBearerRef": "gateway_to_attendance_bearer",
            "attendanceToGatewayBearerRef": "attendance_to_gateway_bearer",
        },
    })
