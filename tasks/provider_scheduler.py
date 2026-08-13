from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import socket
import sys
import time
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from threading import Event, Thread
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

import psycopg2

from gateway_provider import checkin_module, export_module
from gateway_provider.contracts import (
    DeleteMessageAction,
    GatewayEventRequest,
    TelegramCallbackUpdate,
    TelegramEditedMessageUpdate,
    TelegramMessageUpdate,
)
from gateway_provider.gateway_file_client import GatewayFileReader
from gateway_provider.group_route_client import (
    AttendanceGroupRoute,
    GatewayAttendanceGroupRouteReader,
)
from gateway_provider.runtime_security import assert_no_telegram_owner_credentials
from infra.db import database_url_scope
from infra.google_sheets_config import load_google_sheets_config
from infra.shift_web_config import load_shift_web_config
from repositories import worker_action_repo, worker_schedule_repo
from services import attendance_export_service, group_attendance_summary_service
from services.bbq_google_sheets_export_service import (
    sync_bbq_group_month_to_google_sheets,
)
from services.google_sheets_shift_sync_service import sync_shifts_from_google_sheets
from services.test_group_google_sheets_service import (
    sync_test_group_month_to_google_sheets,
)


log = logging.getLogger(__name__)

@dataclass(frozen=True)
class ProviderSchedulerConfig:
    database_url: str
    poll_interval_seconds: float
    lease_seconds: int
    group_summary_enabled: bool
    group_summary_hour: int
    group_summary_minute: int
    group_summary_timezone: str
    group_summary_skip_dates: frozenset[date]
    daily_report_enabled: bool
    daily_report_hour: int
    daily_report_minute: int
    daily_report_timezone: str
    gateway_base_url: str | None = None
    gateway_bearer_token: str | None = None

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("database_url is required")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.lease_seconds < 1 or self.lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        ZoneInfo(self.group_summary_timezone)
        ZoneInfo(self.daily_report_timezone)
        if (self.gateway_base_url is None) != (self.gateway_bearer_token is None):
            raise ValueError(
                "gateway_base_url and gateway_bearer_token must be configured together"
            )
        if (
            self.group_summary_enabled or self.daily_report_enabled
        ) and self.gateway_base_url is None:
            raise ValueError(
                "Gateway dynamic group route directory is required when group schedules are enabled"
            )


@dataclass(frozen=True)
class SchedulerCycleResult:
    claimed_runs: int
    enqueued_actions: int


@dataclass(frozen=True)
class _RunOnceResult:
    claimed: bool
    completed: bool
    operation_count: int


def run_scheduler_cycle(
    config: ProviderSchedulerConfig,
    *,
    worker_id: str,
    now: datetime | None = None,
    sheets_sync: Callable[[], object] | None = None,
    test_group_sync: Callable[..., Awaitable[object]] | None = None,
    bbq_sync: Callable[..., Awaitable[object]] | None = None,
    file_reader: GatewayFileReader | None = None,
    group_route_reader: Callable[[], Sequence[AttendanceGroupRoute]] | None = None,
) -> SchedulerCycleResult:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    claimed = 0
    enqueued = 0
    group_routes: Sequence[AttendanceGroupRoute] = ()
    if config.group_summary_enabled or config.daily_report_enabled:
        if group_route_reader is None:
            if config.gateway_base_url is None or config.gateway_bearer_token is None:
                raise RuntimeError("Gateway dynamic group route directory is unavailable")
            group_route_reader = GatewayAttendanceGroupRouteReader(
                base_url=config.gateway_base_url,
                bearer_token=config.gateway_bearer_token,
            ).read
        group_routes = tuple(group_route_reader())

    deferred_claimed, deferred_actions = run_deferred_interaction_cycle(
        config,
        worker_id=worker_id,
        now=current,
        file_reader=file_reader,
    )
    claimed += deferred_claimed
    enqueued += deferred_actions

    claimed += run_checkin_sheets_sync_cycle(
        config,
        worker_id=worker_id,
        now=current,
        test_group_sync=test_group_sync,
        bbq_sync=bbq_sync,
    )

    summary_date = _due_local_date(
        current,
        timezone_name=config.group_summary_timezone,
        hour=config.group_summary_hour,
        minute=config.group_summary_minute,
    )
    if config.group_summary_enabled:
        for target_date in worker_schedule_repo.list_due_run_dates(
            database_url=config.database_url,
            job_kind="GROUP_SUMMARY",
            run_key_prefix="group-summary:",
            through_date=summary_date,
        ):
            result = _run_once(
                config,
                worker_id=worker_id,
                run_key=f"group-summary:{target_date.isoformat()}",
                job_kind="GROUP_SUMMARY",
                now=current,
                operation=lambda target_date=target_date: _enqueue_group_summaries(
                    config,
                    target_date=target_date,
                    created_at=current,
                    group_routes=group_routes,
                ),
            )
            if result.claimed:
                claimed += 1
                enqueued += result.operation_count
            if not result.completed:
                break

    daily_date = _due_local_date(
        current,
        timezone_name=config.daily_report_timezone,
        hour=config.daily_report_hour,
        minute=config.daily_report_minute,
    )
    if config.daily_report_enabled:
        for report_date in worker_schedule_repo.list_due_run_dates(
            database_url=config.database_url,
            job_kind="DAILY_REPORT",
            run_key_prefix="daily-report:",
            through_date=daily_date,
        ):
            result = _run_once(
                config,
                worker_id=worker_id,
                run_key=f"daily-report:{report_date.isoformat()}",
                job_kind="DAILY_REPORT",
                now=current,
                operation=lambda report_date=report_date: _enqueue_daily_report(
                    config,
                    report_date=report_date,
                    created_at=current,
                    group_routes=group_routes,
                ),
            )
            if result.claimed:
                claimed += 1
                enqueued += result.operation_count
            if not result.completed:
                break

    sheets_config = load_google_sheets_config()
    if sheets_config.enabled:
        interval = sheets_config.sync_interval_seconds
        bucket = int(current.timestamp()) // interval
        year_month = current.astimezone(
            ZoneInfo(load_shift_web_config().timezone_name)
        ).strftime("%Y-%m")
        run_key = f"sheets-sync:{year_month}:{bucket}"

        def run_sheets() -> int:
            with database_url_scope(config.database_url):
                result = (
                    sheets_sync()
                    if sheets_sync is not None
                    else sync_shifts_from_google_sheets(
                        cfg=sheets_config,
                        year_month=year_month,
                    )
                )
            if hasattr(result, "ok") and not bool(getattr(result, "ok")):
                raise RuntimeError(str(getattr(result, "message", "Sheets sync failed")))
            return 0

        result = _run_once(
            config,
            worker_id=worker_id,
            run_key=run_key,
            job_kind="SHEETS_SYNC",
            now=current,
            operation=run_sheets,
        )
        if result.claimed:
            claimed += 1

    return SchedulerCycleResult(claimed, enqueued)


def run_deferred_interaction_cycle(
    config: ProviderSchedulerConfig,
    *,
    worker_id: str,
    now: datetime | None = None,
    file_reader: GatewayFileReader | None = None,
) -> tuple[int, int]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    claimed = 0
    enqueued = 0
    for job_kind, run_key_prefix in (
        ("CHECKIN_PROCESS", "deferred-checkin:"),
        ("ADMIN_EXPORT_PROCESS", "deferred-export:"),
    ):
        due = worker_schedule_repo.list_due_runs(
            database_url=config.database_url,
            job_kind=job_kind,
            run_key_prefix=run_key_prefix,
            now=current,
            limit=100,
        )
        for pending in due:
            event_payload = pending.payload.get("event")
            progress_action_id = pending.payload.get("progressActionId")
            if not isinstance(event_payload, dict) or not isinstance(
                progress_action_id, str
            ):
                raise RuntimeError("invalid deferred interaction payload")
            event = GatewayEventRequest.model_validate(event_payload, strict=True)
            progress_status = worker_schedule_repo.event_action_delivery_status(
                database_url=config.database_url,
                event_id=event.eventId,
                action_id=progress_action_id,
            )
            if progress_status is None:
                continue
            if progress_status != "DELIVERED":
                failed = worker_schedule_repo.fail_waiting_run(
                    database_url=config.database_url,
                    run_key=pending.run_key,
                    job_kind=job_kind,
                    error_code=f"PROGRESS_ACTION_{progress_status}",
                    now=current,
                )
                claimed += int(failed)
                continue
            progress_message_id = (
                worker_schedule_repo.event_action_delivered_message_id(
                    database_url=config.database_url,
                    event_id=event.eventId,
                    action_id=progress_action_id,
                )
            )
            result = _run_once(
                config,
                worker_id=worker_id,
                run_key=pending.run_key,
                job_kind=job_kind,
                now=current,
                operation=lambda event=event, job_kind=job_kind, progress_action_id=progress_action_id, progress_message_id=progress_message_id: _complete_deferred_interaction(
                    config,
                    event=event,
                    job_kind=job_kind,
                    progress_action_id=progress_action_id,
                    progress_message_id=progress_message_id,
                    created_at=current,
                    file_reader=file_reader,
                ),
            )
            if result.claimed:
                claimed += 1
                enqueued += result.operation_count
    return claimed, enqueued


def _complete_deferred_interaction(
    config: ProviderSchedulerConfig,
    *,
    event: GatewayEventRequest,
    job_kind: str,
    progress_action_id: str,
    progress_message_id: int | None,
    created_at: datetime,
    file_reader: GatewayFileReader | None,
) -> int:
    if progress_message_id is None:
        raise RuntimeError("delivered progress action has no Telegram message id")
    owner_prefix = f"deferred-event:{event.eventId}:"
    with psycopg2.connect(config.database_url) as connection:
        with connection.cursor() as cursor:
            existing = worker_action_repo.count_actions_for_owner_prefix_cur(
                cursor,
                owner_prefix=owner_prefix,
            )
            if existing:
                return 0
            update = event.telegramUpdate
            with database_url_scope(config.database_url):
                if job_kind == "CHECKIN_PROCESS":
                    if not isinstance(
                        update,
                        (TelegramMessageUpdate, TelegramEditedMessageUpdate),
                    ):
                        raise RuntimeError("deferred check-in update is invalid")
                    response = checkin_module.process_group_checkin(
                        event,
                        cursor,
                        update,
                        file_reader or _gateway_file_reader(config),
                        defer_long_operation=False,
                    )
                elif job_kind == "ADMIN_EXPORT_PROCESS":
                    if not isinstance(update, TelegramCallbackUpdate):
                        raise RuntimeError("deferred export update is invalid")
                    response = export_module.process_export_callback(
                        event,
                        cursor,
                        update,
                        defer_long_operation=False,
                    )
                else:
                    raise RuntimeError("unsupported deferred interaction kind")
            terminal_actions = [
                action
                for action in response.actions
                if action.actionId not in {
                    progress_action_id,
                    f"{event.eventId}.callback",
                }
            ]
            if not terminal_actions:
                raise RuntimeError("deferred interaction produced no terminal action")
            enqueued = 0
            predecessor_action_id: str | None = None
            for index, action in enumerate(terminal_actions, start=1):
                if (
                    isinstance(action, DeleteMessageAction)
                    and action.messageIdSourceActionId == progress_action_id
                ):
                    action = DeleteMessageAction(
                        actionId=action.actionId,
                        type="DELETE_MESSAGE",
                        chatId=action.chatId,
                        messageId=progress_message_id,
                    )
                result = worker_action_repo.enqueue_action_cur(
                    cursor,
                    owner_key=f"{owner_prefix}{index}",
                    action_kind=f"DEFERRED_{job_kind}",
                    max_attempts=3,
                    predecessor_action_id=predecessor_action_id,
                    request={
                        "protocolVersion": "1.0",
                        "provider": "ATTENDANCE",
                        "correlationId": f"{event.eventId}.deferred.{index}",
                        "targetEventId": event.eventId,
                        "createdAt": _timestamp(created_at),
                        "action": action.model_dump(
                            mode="json",
                            by_alias=True,
                            exclude_none=True,
                        ),
                    },
                )
                enqueued += result == "ENQUEUED"
                predecessor_action_id = action.actionId
    return int(enqueued)


def _gateway_file_reader(config: ProviderSchedulerConfig) -> GatewayFileReader:
    if config.gateway_base_url is None or config.gateway_bearer_token is None:
        raise RuntimeError(
            "Gateway file credentials are required for deferred check-in processing"
        )
    return GatewayFileReader(
        base_url=config.gateway_base_url,
        bearer_token=config.gateway_bearer_token,
    )


def _run_once(
    config: ProviderSchedulerConfig,
    *,
    worker_id: str,
    run_key: str,
    job_kind: str,
    now: datetime,
    operation: Callable[[], int],
) -> _RunOnceResult:
    lease = worker_schedule_repo.claim_run(
        database_url=config.database_url,
        run_key=run_key,
        job_kind=job_kind,
        worker_id=worker_id,
        now=now,
        lease_seconds=config.lease_seconds,
    )
    if lease is None:
        return _RunOnceResult(
            claimed=False,
            completed=worker_schedule_repo.is_run_completed(
                database_url=config.database_url,
                run_key=run_key,
            ),
            operation_count=0,
        )
    heartbeat_stop = Event()
    lease_lost = Event()
    heartbeat_started = time.monotonic()

    def heartbeat() -> None:
        interval = max(0.2, config.lease_seconds / 3)
        while not heartbeat_stop.wait(interval):
            logical_now = now + timedelta(
                seconds=time.monotonic() - heartbeat_started
            )
            if not worker_schedule_repo.renew_run(
                database_url=config.database_url,
                run_key=run_key,
                worker_id=worker_id,
                lease_version=lease.lease_version,
                now=logical_now,
                lease_seconds=config.lease_seconds,
            ):
                lease_lost.set()
                return

    heartbeat_thread = Thread(
        target=heartbeat,
        name=f"attendance-scheduler-lease-{job_kind.lower()}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        operation_count = operation()
        heartbeat_stop.set()
        heartbeat_thread.join()
        if lease_lost.is_set():
            raise RuntimeError("scheduler lease was lost during operation")
        completed_at = now + timedelta(
            seconds=time.monotonic() - heartbeat_started
        )
        worker_schedule_repo.complete_run(
            database_url=config.database_url,
            run_key=run_key,
            worker_id=worker_id,
            lease_version=lease.lease_version,
            now=completed_at,
        )
    except Exception as error:
        heartbeat_stop.set()
        heartbeat_thread.join()
        if not lease_lost.is_set():
            failed_at = now + timedelta(
                seconds=time.monotonic() - heartbeat_started
            )
            worker_schedule_repo.retry_run(
                database_url=config.database_url,
                run_key=run_key,
                worker_id=worker_id,
                lease_version=lease.lease_version,
                now=failed_at,
                error_code=type(error).__name__,
            )
        log.exception("Attendance scheduler job failed kind=%s key=%s", job_kind, run_key)
        return _RunOnceResult(claimed=True, completed=False, operation_count=0)
    return _RunOnceResult(
        claimed=True,
        completed=True,
        operation_count=operation_count,
    )


def run_checkin_sheets_sync_cycle(
    config: ProviderSchedulerConfig,
    *,
    worker_id: str,
    now: datetime | None = None,
    test_group_sync: Callable[..., Awaitable[object]] | None = None,
    bbq_sync: Callable[..., Awaitable[object]] | None = None,
) -> int:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    due = worker_schedule_repo.list_due_runs(
        database_url=config.database_url,
        job_kind="CHECKIN_SHEETS_SYNC",
        run_key_prefix="checkin-sheets:",
        now=current,
        limit=100,
    )
    claimed = 0
    for pending in due:
        sync_kind = str(pending.payload.get("syncKind") or "")
        chat_id = pending.payload.get("chatId")
        if sync_kind not in {"TEST_GROUP", "BBQ"} or not isinstance(chat_id, int):
            raise RuntimeError("invalid persisted check-in Sheets sync payload")

        def run_sync(
            *,
            sync_kind: str = sync_kind,
            chat_id: int = chat_id,
        ) -> int:
            with database_url_scope(config.database_url):
                if sync_kind == "TEST_GROUP":
                    result = asyncio.run(
                        (test_group_sync or sync_test_group_month_to_google_sheets)(
                            chat_id=chat_id
                        )
                    )
                else:
                    result = asyncio.run(
                        (bbq_sync or sync_bbq_group_month_to_google_sheets)(
                            chat_id=chat_id
                        )
                    )
            if not bool(getattr(result, "ok", False)):
                raise RuntimeError(str(getattr(result, "message", "Sheets sync failed")))
            return 0

        result = _run_once(
            config,
            worker_id=worker_id,
            run_key=pending.run_key,
            job_kind="CHECKIN_SHEETS_SYNC",
            now=current,
            operation=run_sync,
        )
        if result.claimed:
            claimed += 1
    return claimed


def _enqueue_group_summaries(
    config: ProviderSchedulerConfig,
    *,
    target_date: date,
    created_at: datetime,
    group_routes: Sequence[AttendanceGroupRoute],
) -> int:
    if target_date in config.group_summary_skip_dates:
        return 0
    enqueued = 0
    with database_url_scope(config.database_url):
        for group_route in group_routes:
            chat_id = group_route.chat_id
            rows = group_attendance_summary_service.build_rows_for_group(
                chat_id=chat_id,
                target_date=target_date,
            )
            if not rows:
                continue
            text = group_attendance_summary_service.summarize_text(
                rows=rows,
                target_date=target_date,
                chat_id=chat_id,
            )
            action_id = (
                f"attendance.group-summary.{target_date.isoformat()}.{abs(chat_id)}"
            )
            result = worker_action_repo.enqueue_action(
                database_url=config.database_url,
                owner_key=f"{target_date.isoformat()}:{chat_id}",
                action_kind="GROUP_SUMMARY",
                max_attempts=3,
                request=_message_request(
                    action_id=action_id,
                    created_at=created_at,
                    route_key=group_route.route_ref,
                    text=text,
                ),
            )
            enqueued += result == "ENQUEUED"
    return int(enqueued)


def _enqueue_daily_report(
    config: ProviderSchedulerConfig,
    *,
    report_date: date,
    created_at: datetime,
    group_routes: Sequence[AttendanceGroupRoute],
) -> int:
    with database_url_scope(config.database_url):
        rows = asyncio.run(
            attendance_export_service.collect_rows_for_date(
                target_date=report_date,
            )
        )
        csv_bytes = group_attendance_summary_service.encode_csv(rows=rows)
    enqueued = 0
    for group_route in group_routes:
        route_suffix = hashlib.sha256(group_route.route_ref.encode("utf-8")).hexdigest()[:12]
        action_id = (
            f"attendance.daily-report.{report_date.isoformat()}.{route_suffix}"
        )
        request = {
            "protocolVersion": "1.0",
            "provider": "ATTENDANCE",
            "correlationId": action_id,
            "createdAt": _timestamp(created_at),
            "action": {
                "actionId": action_id,
                "type": "SEND_GROUP_DOCUMENT",
                "routeKey": group_route.route_ref,
                "document": {
                    "source": "BYTES",
                    "contentBase64": base64.b64encode(csv_bytes).decode("ascii"),
                    "fileName": f"attendance_{report_date.isoformat()}.csv",
                    "mimeType": "text/csv; charset=utf-8",
                },
            },
        }
        result = worker_action_repo.enqueue_action(
            database_url=config.database_url,
            owner_key=f"{report_date.isoformat()}:{group_route.route_ref}",
            action_kind="DAILY_REPORT",
            max_attempts=3,
            request=request,
        )
        enqueued += result == "ENQUEUED"
    return int(enqueued)


def _message_request(
    *, action_id: str, created_at: datetime, route_key: str, text: str
) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "provider": "ATTENDANCE",
        "correlationId": action_id,
        "createdAt": _timestamp(created_at),
        "action": {
            "actionId": action_id,
            "type": "SEND_GROUP_MESSAGE",
            "routeKey": route_key,
            "text": text,
        },
    }


def _due_local_date(
    now: datetime, *, timezone_name: str, hour: int, minute: int
) -> date:
    local = now.astimezone(ZoneInfo(timezone_name))
    if local.time() >= wall_time(hour, minute):
        return local.date()
    return local.date() - timedelta(days=1)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_scheduler_config(environment: dict[str, str]) -> ProviderSchedulerConfig:
    if not _enabled(environment, "ATTENDANCE_PROVIDER_SCHEDULER_ENABLED", False):
        raise RuntimeError("ATTENDANCE_PROVIDER_SCHEDULER_ENABLED=true is required")
    summary_hour, summary_minute = _hour_minute(
        environment.get("GROUP_DAILY_SUMMARY_TIME") or "23:30"
    )
    daily_hour = _bounded_int(
        environment.get("DAILY_ATTENDANCE_REPORT_HOUR") or "23", 0, 23
    )
    daily_minute = _bounded_int(
        environment.get("DAILY_ATTENDANCE_REPORT_MINUTE") or "0", 0, 59
    )
    skip_raw = (environment.get("GROUP_DAILY_SUMMARY_SKIP_DATE") or "").replace("，", ",")
    skip_dates = frozenset(
        date.fromisoformat(value.strip())
        for value in skip_raw.split(",")
        if value.strip()
    )
    return ProviderSchedulerConfig(
        database_url=_required(environment, "ATTENDANCE_DATABASE_URL"),
        poll_interval_seconds=float(
            environment.get("ATTENDANCE_PROVIDER_SCHEDULER_POLL_SECONDS") or "30"
        ),
        lease_seconds=int(
            environment.get("ATTENDANCE_PROVIDER_SCHEDULER_LEASE_SECONDS") or "300"
        ),
        group_summary_enabled=_enabled(
            environment, "GROUP_DAILY_SUMMARY_ENABLED", True
        ),
        group_summary_hour=summary_hour,
        group_summary_minute=summary_minute,
        group_summary_timezone=(
            environment.get("GROUP_DAILY_SUMMARY_TZ") or "Asia/Shanghai"
        ).strip(),
        group_summary_skip_dates=skip_dates,
        daily_report_enabled=_enabled(
            environment, "DAILY_ATTENDANCE_REPORT_ENABLED", True
        ),
        daily_report_hour=daily_hour,
        daily_report_minute=daily_minute,
        daily_report_timezone=(
            environment.get("DAILY_ATTENDANCE_REPORT_TIMEZONE") or "Asia/Shanghai"
        ).strip(),
        gateway_base_url=_required(environment, "GATEWAY_INTERNAL_BASE_URL"),
        gateway_bearer_token=_required(
            environment,
            "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN",
        ),
    )


def main(arguments: Sequence[str] | None = None) -> int:
    assert_no_telegram_owner_credentials(os.environ)
    args = list(arguments if arguments is not None else sys.argv[1:])
    if args not in ([], ["--once"]):
        raise RuntimeError("usage: python -m tasks.provider_scheduler [--once]")
    config = load_scheduler_config(dict(os.environ))
    worker_action_repo.assert_schema_ready(database_url=config.database_url)
    worker_schedule_repo.assert_schema_ready(database_url=config.database_url)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    if args == ["--once"]:
        run_scheduler_cycle(config, worker_id=worker_id)
        return 0
    while True:
        try:
            run_scheduler_cycle(config, worker_id=worker_id)
        except Exception:
            log.exception("Attendance provider scheduler cycle failed")
        time.sleep(config.poll_interval_seconds)


def _enabled(environment: dict[str, str], name: str, default: bool) -> bool:
    raw = environment.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _required(environment: dict[str, str], name: str) -> str:
    value = (environment.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _hour_minute(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("GROUP_DAILY_SUMMARY_TIME must be HH:MM")
    return _bounded_int(parts[0], 0, 23), _bounded_int(parts[1], 0, 59)


def _bounded_int(value: str, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"value must be between {minimum} and {maximum}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
