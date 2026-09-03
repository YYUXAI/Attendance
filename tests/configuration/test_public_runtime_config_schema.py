from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from infra.public_runtime_plan import (
    ROOT_DERIVED_ATTENDANCE_ENVIRONMENT,
    derive_attendance_public_runtime_plan,
)
from infra.attendance_group_policy import load_group_policies, normalize_group_policies


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
    assert config["sheets"]["primary"]["spreadsheetId"] == "primary-sheet-id"


def test_attendance_runtime_plan_contains_only_public_env_and_file_mappings() -> None:
    plan = derive_attendance_public_runtime_plan(_fixture())
    assert plan.public_environment["SHIFT_WEB_PORT"] == "19084"
    assert plan.public_environment["SHIFT_WEB_APP_PUBLIC_URL"].endswith("/attendance")
    assert plan.public_environment["GROUP_DAILY_SUMMARY_ENABLED"] == "false"
    assert plan.public_environment["DAILY_ATTENDANCE_REPORT_ENABLED"] == "true"
    assert plan.public_environment["ATTENDANCE_PROVIDER_SCHEDULER_ENABLED"] == "true"
    assert "ATTENDANCE_PROVIDER_SCHEDULER_ENABLED" in plan.public_environment
    assert "sheetSyncIntervalSeconds" not in repr(plan)
    policies = load_group_policies(plan.public_environment)
    assert policies[0].title == "ux助手考勤测试群"
    assert policies[0].roster == "main"
    assert policies[0].capabilities == frozenset({"standard-checkin"})
    assert "GATEWAY_ATTENDANCE_CHAT_IDS" not in plan.public_environment
    assert "GROUP_DAILY_SUMMARY_ROUTE_KEYS_JSON" not in plan.public_environment
    assert "DAILY_ATTENDANCE_REPORT_ROUTE_KEY" not in plan.public_environment
    assert "FORMAL_GROUP_ROSTER_SOURCE_MAP" not in plan.public_environment
    assert "ATTENDANCE_DATABASE_URL" not in plan.public_environment
    assert plan.public_environment["ATTENDANCE_DATABASE_NAME"] == "attendance_v1"
    assert "GATEWAY_TO_ATTENDANCE_BEARER_TOKEN" not in plan.public_environment
    assert plan.public_environment["GOOGLE_SHEETS_SPREADSHEET_ID"] == "primary-sheet-id"
    assert plan.public_environment["GOOGLE_SHEETS_SHEET_GID"] == "757170338"
    assert plan.public_environment["CHECKIN_AI_API_KEY_REQUIRED"] == "true"
    assert plan.public_environment["GOOGLE_SHEETS_CREDENTIALS_REQUIRED"] == "false"
    assert plan.public_environment["TEST_GROUP_ATTENDANCE_SHEET_TITLE"] == "Attendance"
    assert all(
        target.endswith("_FILE")
        for binding in plan.file_bindings
        for target in binding.target_file_variables
    )
    assert plan.derived_private_files == ()
    bindings = {binding.binding_ref: binding for binding in plan.file_bindings}
    assert bindings["attendance_ai_api_key"].components == ("provider", "scheduler")
    assert bindings["attendance_webapp_session_signing"].components == ("webapp",)
    rendered = repr(plan)
    assert "postgresql://" not in rendered


def test_disabled_ai_does_not_require_premium_key_and_webapp_signing_is_always_required() -> None:
    config = _fixture()
    config["ai"]["enabled"] = False
    config["ai"]["mode"] = "assist"
    plan = derive_attendance_public_runtime_plan(config)
    bindings = {binding.binding_ref: binding for binding in plan.file_bindings}

    assert plan.public_environment["CHECKIN_AI_PREMIUM_API_KEY_REQUIRED"] == "false"
    assert bindings["attendance_webapp_session_signing"].required_when == "always"


def test_group_policy_supports_zero_one_or_many_and_standard_default() -> None:
    assert normalize_group_policies([]) == ()
    policies = normalize_group_policies([
        {"title": "private group", "roster": "main"},
        {
            "title": "public group",
            "roster": "alt",
            "capabilities": ["premium-ai", "pc-only-screenshot"],
        },
    ])
    assert policies[0].capabilities == frozenset({"standard-checkin"})
    assert policies[1].capabilities == frozenset({"premium-ai", "pc-only-screenshot"})


def test_group_policy_rejects_duplicate_unknown_and_conflicting_configuration() -> None:
    invalid = (
        [
            {"title": "same", "roster": "main"},
            {"title": "same", "roster": "alt"},
        ],
        [{"title": "one", "roster": "unknown"}],
        [{"title": "one", "roster": "main", "capabilities": ["unknown"]}],
        [{
            "title": "one",
            "roster": "main",
            "capabilities": ["standard-checkin", "remote-diff-checkin"],
        }],
        [{
            "title": "one",
            "roster": "main",
            "capabilities": ["test-group-google-sheets", "bbq-google-sheets"],
        }],
    )
    for value in invalid:
        try:
            normalize_group_policies(value)
        except ValueError:
            continue
        raise AssertionError(f"invalid group policy was accepted: {value!r}")


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
    secret_targets.add("OCRSPACE_API_KEY")
    identifier_targets = {
        target.removesuffix("_FILE")
        for derived in plan.derived_private_files
        for target in derived["targetFileVariables"]
        if target != "GROUP_DAILY_SUMMARY_ROUTE_KEYS_JSON_FILE"
    }

    assert set(inventory["public"]) <= public_targets
    assert set(inventory["sensitive_secret"]) - {"ATTENDANCE_DATABASE_URL"} <= secret_targets
    assert "ATTENDANCE_DATABASE_PASSWORD" in secret_targets
    assert set(inventory["sensitive_identifier"]) <= identifier_targets
    assert set(inventory["derived_runtime_value"]) <= (
        public_targets | set(ROOT_DERIVED_ATTENDANCE_ENVIRONMENT)
    )
    assert not set(inventory["business_database_truth"]) & (public_targets | secret_targets | identifier_targets)


def _fixture() -> dict[str, object]:
    return deepcopy({
        "groups": [
            {
                "title": "ux助手考勤测试群",
                "roster": "main",
                "capabilities": ["standard-checkin"],
            }
        ],
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
            "publicBaseUrl": "https://ux-assistant-test.example.invalid/attendance",
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
                "remoteDiff": {
                    "enabled": False,
                    "timezone": "Asia/Shanghai",
                    "spreadsheetId": "remote-sheet-id",
                    "sheetGid": 2,
                },
                "testGroup": {
                    "enabled": False,
                    "timezone": "Asia/Shanghai",
                    "slackCheckin": True,
                    "shiftSpreadsheetId": "shift-sheet-id",
                    "shiftSheetGid": 3,
                    "attendanceSpreadsheetId": "attendance-sheet-id",
                    "attendanceSheetGid": 4,
                    "attendanceSheetTitle": "Attendance",
                },
                "bbq": {
                    "enabled": False,
                    "timezone": "Asia/Shanghai",
                    "spreadsheetId": "bbq-sheet-id",
                    "sheetTitle": "BBQ",
                },
            },
            "primary": {"spreadsheetId": "primary-sheet-id", "sheetGid": 757170338},
            "alternate": {"spreadsheetId": "alternate-sheet-id", "sheetGid": 1},
            "credentialsSecretRef": "attendance_google_service_account",
        },
        "scheduler": {
            "enabled": True,
            "pollSeconds": 30,
            "leaseSeconds": 300,
            "timezone": "Asia/Shanghai",
            "dailySummaryEnabled": False,
            "dailySummaryTime": "23:30",
            "dailySummarySkipDate": "",
            "shiftStartNoticeEnabled": False,
            "dailyReportEnabled": True,
            "dailyReportTime": "23:00",
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
