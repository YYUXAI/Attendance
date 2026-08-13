"""Pure public-manifest to Attendance runtime mapping; never resolves bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ROOT_DERIVED_ATTENDANCE_ENVIRONMENT = ("CHECKIN_AI_TESSERACT_CMD",)


@dataclass(frozen=True)
class FileBinding:
    binding_ref: str
    category: str
    target_file_variables: tuple[str, ...]
    required_when: str


@dataclass(frozen=True)
class AttendancePublicRuntimePlan:
    public_environment: dict[str, str]
    file_bindings: tuple[FileBinding, ...]
    derived_private_files: tuple[dict[str, object], ...]


def derive_attendance_public_runtime_plan(
    config: dict[str, Any],
) -> AttendancePublicRuntimePlan:
    provider = config["provider"]
    webapp = config["webapp"]
    ai = config["ai"]
    sheets = config["sheets"]
    scheduler = config["scheduler"]
    worker = config["worker"]
    observability = config["observability"]
    sheet_profiles = sheets["profiles"]
    daily_report_hour, daily_report_minute = str(scheduler["dailyReportTime"]).split(":")

    return AttendancePublicRuntimePlan(
        public_environment={
            "GATEWAY_ENABLED": "true",
            "SHIFT_WEB_ENABLED": _enabled(webapp["enabled"]),
            "SHIFT_WEB_APP_PUBLIC_URL": str(webapp["publicBaseUrl"]),
            "SHIFT_WEB_HOST": str(webapp["host"]),
            "SHIFT_WEB_PORT": str(webapp["port"]),
            "SHIFT_WEB_TIMEZONE": str(webapp["timezone"]),
            "SHIFT_WEB_BROWSER_DEV": _enabled(webapp["browserDev"]),
            "CHECKIN_AI_ENABLED": _enabled(ai["enabled"]),
            "CHECKIN_AI_EXTRACT_BACKEND": str(ai["extractBackend"]),
            "CHECKIN_AI_BASE_URL": str(ai["apiBaseUrl"]),
            "CHECKIN_AI_MODEL": str(ai["model"]),
            "CHECKIN_AI_TEXT_MODEL": str(ai["textModel"]),
            "CHECKIN_AI_MODE": str(ai["mode"]),
            "CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES": str(ai["maxClockSkewMinutes"]),
            "CHECKIN_AI_TIMEOUT_SECONDS": str(ai["timeoutSeconds"]),
            "CHECKIN_AI_TRUST_SENDER_WHEN_NAME_UNREADABLE": _enabled(
                ai["trustSenderWhenNameUnreadable"]
            ),
            "CHECKIN_AI_NAME_VERIFY": str(ai["nameVerify"]),
            "CHECKIN_AI_CLOCK_FALLBACK_SEND_TIME": _enabled(
                ai["clockFallbackSendTime"]
            ),
            "CHECKIN_AI_OCR_ENGINE": str(ai["ocr"]["engine"]),
            "CHECKIN_AI_EASYOCR_GPU": _enabled(ai["ocr"]["easyOcrGpu"]),
            "CHECKIN_AI_OCR_MAX_CONCURRENT": str(ai["ocr"]["maxConcurrent"]),
            "CHECKIN_AI_PREMIUM_ENABLED": _enabled(ai["premium"]["enabled"]),
            "CHECKIN_AI_PREMIUM_BASE_URL": str(ai["premium"]["apiBaseUrl"]),
            "CHECKIN_AI_PREMIUM_MODEL": str(ai["premium"]["model"]),
            "GOOGLE_SHEETS_ENABLED": _enabled(sheets["enabled"]),
            "GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS": str(sheets["syncIntervalSeconds"]),
            "GOOGLE_SHEETS_YEAR_MONTH": str(sheets["yearMonth"]),
            "REMOTE_DIFF_GOOGLE_SHEETS_ENABLED": _enabled(
                sheet_profiles["remoteDiff"]["enabled"]
            ),
            "REMOTE_DIFF_GOOGLE_SHEETS_TIMEZONE": str(
                sheet_profiles["remoteDiff"]["timezone"]
            ),
            "TEST_GROUP_GOOGLE_SHEETS_ENABLED": _enabled(
                sheet_profiles["testGroup"]["enabled"]
            ),
            "TEST_GROUP_GOOGLE_SHEETS_TIMEZONE": str(
                sheet_profiles["testGroup"]["timezone"]
            ),
            "TEST_GROUP_ATTENDANCE_SHEET_TITLE": str(
                sheet_profiles["testGroup"]["attendanceSheetTitle"]
            ),
            "TEST_GROUP_SLACK_CHECKIN": _enabled(
                sheet_profiles["testGroup"]["slackCheckin"]
            ),
            "BBQ_GOOGLE_SHEETS_ENABLED": _enabled(sheet_profiles["bbq"]["enabled"]),
            "BBQ_GOOGLE_SHEETS_TIMEZONE": str(sheet_profiles["bbq"]["timezone"]),
            "BBQ_GOOGLE_SHEETS_SHEET_TITLE": str(sheet_profiles["bbq"]["sheetTitle"]),
            "GROUP_DAILY_SUMMARY_ENABLED": _enabled(scheduler["enabled"]),
            "GROUP_DAILY_SUMMARY_TIME": str(scheduler["dailySummaryTime"]),
            "GROUP_DAILY_SUMMARY_TZ": str(scheduler["timezone"]),
            "GROUP_DAILY_SUMMARY_SKIP_DATE": str(scheduler["dailySummarySkipDate"]),
            "ATTENDANCE_PROVIDER_SCHEDULER_ENABLED": _enabled(scheduler["enabled"]),
            "ATTENDANCE_PROVIDER_SCHEDULER_POLL_SECONDS": str(scheduler["pollSeconds"]),
            "ATTENDANCE_PROVIDER_SCHEDULER_LEASE_SECONDS": str(scheduler["leaseSeconds"]),
            "DAILY_ATTENDANCE_REPORT_ENABLED": _enabled(scheduler["dailyReportEnabled"]),
            "DAILY_ATTENDANCE_REPORT_HOUR": daily_report_hour,
            "DAILY_ATTENDANCE_REPORT_MINUTE": daily_report_minute,
            "DAILY_ATTENDANCE_REPORT_TIMEZONE": str(scheduler["timezone"]),
            "ATTENDANCE_PROVIDER_WORKER_ENABLED": _enabled(worker["enabled"]),
            "ATTENDANCE_PROVIDER_WORKER_POLL_SECONDS": str(worker["pollSeconds"]),
            "ATTENDANCE_PROVIDER_WORKER_LEASE_SECONDS": str(worker["leaseSeconds"]),
            "ATTENDANCE_PROVIDER_WORKER_BATCH_SIZE": str(worker["batchSize"]),
            "ATTENDANCE_PROVIDER_WORKER_TIMEOUT_SECONDS": str(worker["timeoutSeconds"]),
            "ATTENDANCE_PROVIDER_WORKER_MAX_ACCEPTANCE_ATTEMPTS": str(
                worker["maximumAcceptanceAttempts"]
            ),
            "GATEWAY_INTERNAL_BASE_URL": "http://gateway-real:19081",
            "ATTENDANCE_PROVIDER_HOST": str(provider["host"]),
            "ATTENDANCE_PROVIDER_PORT": str(provider["port"]),
            "LOG_LEVEL": str(observability["logLevel"]),
        },
        file_bindings=(
            _secret("attendance_database_url", "always", "ATTENDANCE_DATABASE_URL_FILE"),
            _secret(
                "gateway_to_attendance_bearer",
                "provider",
                "GATEWAY_TO_ATTENDANCE_BEARER_TOKEN_FILE",
            ),
            _secret(
                "attendance_to_gateway_bearer",
                "provider-worker-scheduler",
                "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN_FILE",
            ),
            _secret(
                "attendance_webapp_session_signing",
                "webapp.enabled",
                "GATEWAY_WEBAPP_SESSION_SIGNING_SECRET_FILE",
            ),
            _secret(
                "attendance_ai_api_key",
                "ai.enabled",
                "CHECKIN_AI_API_KEY_FILE",
                "ZAI_API_KEY_FILE",
                "ZHIPU_API_KEY_FILE",
            ),
            _secret(
                "attendance_premium_ai_api_key",
                "ai.premium.enabled",
                "CHECKIN_AI_PREMIUM_API_KEY_FILE",
                "ZHIPU_PREMIUM_API_KEY_FILE",
            ),
            _secret(
                "attendance_google_service_account",
                "sheets.enabled",
                "GOOGLE_SHEETS_CREDENTIALS_JSON_FILE",
                "GOOGLE_SHEETS_ALT_CREDENTIALS_JSON_FILE",
                "REMOTE_DIFF_GOOGLE_SHEETS_CREDENTIALS_JSON_FILE",
                "TEST_GROUP_GOOGLE_SHEETS_CREDENTIALS_JSON_FILE",
                "BBQ_GOOGLE_SHEETS_CREDENTIALS_JSON_FILE",
            ),
        ),
        derived_private_files=(
            {
                "bindingRef": "attendance_google_sheet_objects",
                "targetFileVariables": [
                    "GOOGLE_SHEETS_SPREADSHEET_ID_FILE",
                    "GOOGLE_SHEETS_SHEET_GID_FILE",
                    "GOOGLE_SHEETS_ALT_SPREADSHEET_ID_FILE",
                    "GOOGLE_SHEETS_ALT_SHEET_GID_FILE",
                    "REMOTE_DIFF_GOOGLE_SHEETS_SPREADSHEET_ID_FILE",
                    "REMOTE_DIFF_GOOGLE_SHEETS_SHEET_GID_FILE",
                    "TEST_GROUP_ATTENDANCE_SPREADSHEET_ID_FILE",
                    "TEST_GROUP_ATTENDANCE_SHEET_GID_FILE",
                    "TEST_GROUP_SHIFT_SPREADSHEET_ID_FILE",
                    "TEST_GROUP_SHIFT_SHEET_GID_FILE",
                    "BBQ_GOOGLE_SHEETS_SPREADSHEET_ID_FILE",
                ],
                "publicContext": {"enabled": sheets["enabled"]},
            },
        ),
    )


def _enabled(value: bool) -> str:
    return "true" if value else "false"


def _secret(binding_ref: str, required_when: str, *targets: str) -> FileBinding:
    return FileBinding(binding_ref, "sensitive_secret", tuple(targets), required_when)
