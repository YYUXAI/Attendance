from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any

import psycopg2
import pytest
from fastapi.testclient import TestClient

from gateway_provider.app import (
    AttendanceGatewayProviderConfig,
    create_attendance_gateway_provider_app,
)
from repositories import worker_action_repo
from tasks import provider_worker


_ROOT_ACTION_ID = "attendance.worker.integration.1001"
_GATEWAY_CREDENTIAL = "gateway-to-attendance-worker-test-token"
_ATTENDANCE_CREDENTIAL = "attendance-to-gateway-worker-test-token"
def _database_url() -> str:
    value = (os.environ.get("ATTENDANCE_TEST_DATABASE_URL") or "").strip()
    if not value:
        pytest.skip("ATTENDANCE_TEST_DATABASE_URL is required")
    return value


def _prepare_database() -> None:
    root = Path(__file__).resolve().parent
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for name in (
                "0003_gateway_provider.sql",
                "0006_delivery_receipts.sql",
                "0008_worker_checkin_recovery.sql",
                "0009_durable_provider_worker.sql",
                "0010_scheduler_fencing_and_sheets_outbox.sql",
                "0011_worker_action_dependencies.sql",
            ):
                cursor.execute((root / "migrations" / name).read_text(encoding="utf-8"))
            cursor.execute(
                "DELETE FROM attendance_gateway_delivery_receipts "
                "WHERE action_id LIKE 'attendance.worker.integration.%'",
            )
            cursor.execute(
                "DELETE FROM attendance_worker_action_attempts",
            )
            cursor.execute(
                "DELETE FROM attendance_worker_actions",
            )


class _FakeGateway:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                assert self.path == "/internal/v1/actions"
                assert self.headers["Authorization"] == (
                    f"Bearer {_ATTENDANCE_CREDENTIAL}"
                )
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                requests.append(payload)
                response = {
                    "protocolVersion": "1.0",
                    "actionId": payload["action"]["actionId"],
                    "result": "ACCEPTED",
                }
                body = json.dumps(response).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "_FakeGateway":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _run_worker_once(gateway_base_url: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    for name in (
        "BOT_TOKEN",
        "SHIFT_WEB_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TG_BOT_TOKEN",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "ATTENDANCE_DATABASE_URL": _database_url(),
            "GATEWAY_INTERNAL_BASE_URL": gateway_base_url,
            "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN": _ATTENDANCE_CREDENTIAL,
            "ATTENDANCE_PROVIDER_WORKER_ENABLED": "true",
            "ATTENDANCE_PROVIDER_WORKER_LEASE_SECONDS": "2",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "tasks.provider_worker", "--once"],
        cwd=Path(__file__).resolve().parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _provider_client() -> TestClient:
    return TestClient(
        create_attendance_gateway_provider_app(
            AttendanceGatewayProviderConfig(
                database_url=_database_url(),
                gateway_to_attendance_bearer_token=_GATEWAY_CREDENTIAL,
                gateway_internal_base_url="http://127.0.0.1:19081",
                attendance_to_gateway_bearer_token=_ATTENDANCE_CREDENTIAL,
                shift_web_app_public_url="https://attendance.example.test",
            )
        )
    )


def _delete_worker_action(action_id: str) -> None:
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_gateway_delivery_receipts "
                "WHERE action_id LIKE %s",
                (f"{action_id}%",),
            )
            cursor.execute(
                "DELETE FROM attendance_worker_actions WHERE action_id = %s",
                (action_id,),
            )


def _worker_environment(gateway_base_url: str, *, lease_seconds: int) -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "BOT_TOKEN",
        "SHIFT_WEB_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TG_BOT_TOKEN",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "ATTENDANCE_DATABASE_URL": _database_url(),
            "GATEWAY_INTERNAL_BASE_URL": gateway_base_url,
            "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN": _ATTENDANCE_CREDENTIAL,
            "ATTENDANCE_PROVIDER_WORKER_ENABLED": "true",
            "ATTENDANCE_PROVIDER_WORKER_LEASE_SECONDS": str(lease_seconds),
            "ATTENDANCE_PROVIDER_WORKER_TIMEOUT_SECONDS": "5",
        }
    )
    return environment


def _worker_request(action_id: str, *, text: str) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "provider": "ATTENDANCE",
        "correlationId": action_id,
        "createdAt": "2026-08-09T10:00:00Z",
        "action": {
            "actionId": action_id,
            "type": "SEND_GROUP_MESSAGE",
            "routeKey": "group-route.attendance.worker-test",
            "text": text,
        },
    }


class _BlockingFakeGateway:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.received = Event()
        self.release = Event()
        requests = self.requests
        received = self.received
        release = self.release

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                requests.append(json.loads(self.rfile.read(length)))
                received.set()
                release.wait(timeout=5)

            def log_message(self, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "_BlockingFakeGateway":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def test_worker_delivers_a_durable_action_and_receipt_finishes_it_once() -> None:
    _prepare_database()
    request = {
        "protocolVersion": "1.0",
        "provider": "ATTENDANCE",
        "correlationId": _ROOT_ACTION_ID,
        "createdAt": "2026-08-09T10:00:00Z",
        "action": {
            "actionId": _ROOT_ACTION_ID,
            "type": "SEND_GROUP_MESSAGE",
            "routeKey": "group-route.attendance.worker-test",
            "text": "考勤提醒：请及时打卡。",
        },
    }
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="notification:1001",
        request=request,
        max_attempts=3,
    )

    with _FakeGateway() as gateway:
        first = _run_worker_once(gateway.base_url)
        assert first.returncode == 0, first.stderr
        assert gateway.requests == [request]

        receipt = _provider_client().post(
            "/integration/gateway/v1/delivery-receipts",
            headers={"Authorization": f"Bearer {_GATEWAY_CREDENTIAL}"},
            json={
                "protocolVersion": "1.0",
                "receiptId": "receipt.attendance.worker.integration.1001",
                "provider": "ATTENDANCE",
                "actionId": _ROOT_ACTION_ID,
                "correlationId": _ROOT_ACTION_ID,
                "status": "DELIVERED",
                "attemptedAt": "2026-08-09T10:00:01Z",
                "telegramResult": {
                    "accepted": True,
                    "messageId": 91001,
                },
            },
        )
        assert receipt.status_code == 200, receipt.text

        restarted = _run_worker_once(gateway.base_url)
        assert restarted.returncode == 0, restarted.stderr
        assert gateway.requests == [request]

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt_count, last_attempt_action_id
                FROM attendance_worker_actions
                WHERE action_id = %s
                """,
                (_ROOT_ACTION_ID,),
            )
            assert cursor.fetchone() == ("DELIVERED", 1, _ROOT_ACTION_ID)


def test_concurrent_worker_processes_claim_one_action_once() -> None:
    _prepare_database()
    action_id = "attendance.worker.integration.1002"
    _delete_worker_action(action_id)
    request = _worker_request(action_id, text="并发领取测试")
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="notification:1002",
        request=request,
        max_attempts=3,
    )

    with _FakeGateway() as gateway:
        command = [sys.executable, "-m", "tasks.provider_worker", "--once"]
        environment = _worker_environment(gateway.base_url, lease_seconds=2)
        first = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        second = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, first_stderr = first.communicate(timeout=10)
        _, second_stderr = second.communicate(timeout=10)

    assert first.returncode == 0, first_stderr
    assert second.returncode == 0, second_stderr
    assert gateway.requests == [request]


def test_expired_lease_restarts_the_same_gateway_action_id() -> None:
    _prepare_database()
    action_id = "attendance.worker.integration.1003"
    _delete_worker_action(action_id)
    request = _worker_request(action_id, text="崩溃恢复测试")
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="notification:1003",
        request=request,
        max_attempts=3,
    )

    with _BlockingFakeGateway() as blocked_gateway:
        crashed = subprocess.Popen(
            [sys.executable, "-m", "tasks.provider_worker", "--once"],
            cwd=Path(__file__).resolve().parent,
            env=_worker_environment(blocked_gateway.base_url, lease_seconds=1),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert blocked_gateway.received.wait(timeout=5)
        crashed.terminate()
        crashed.communicate(timeout=5)
        assert crashed.returncode != 0

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with psycopg2.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT lease_expires_at <= clock_timestamp()
                    FROM attendance_worker_actions
                    WHERE action_id = %s
                    """,
                    (action_id,),
                )
                if cursor.fetchone() == (True,):
                    break
        time.sleep(0.05)
    else:
        raise AssertionError("worker lease did not expire")

    with _FakeGateway() as recovered_gateway:
        recovered = subprocess.run(
            [sys.executable, "-m", "tasks.provider_worker", "--once"],
            cwd=Path(__file__).resolve().parent,
            env=_worker_environment(recovered_gateway.base_url, lease_seconds=1),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    assert recovered.returncode == 0, recovered.stderr
    assert recovered_gateway.requests == [request]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT root.status, root.attempt_count,
                       attempt.acceptance_attempt_count
                FROM attendance_worker_actions AS root
                JOIN attendance_worker_action_attempts AS attempt
                  ON attempt.attempt_action_id = root.last_attempt_action_id
                WHERE root.action_id = %s
                """,
                (action_id,),
            )
            assert cursor.fetchone() == ("SUBMITTED", 1, 2)


def test_retryable_receipt_creates_one_successor_attempt() -> None:
    _prepare_database()
    action_id = "attendance.worker.integration.1004"
    _delete_worker_action(action_id)
    request = _worker_request(action_id, text="回执重试测试")
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="notification:1004",
        request=request,
        max_attempts=3,
    )

    with _FakeGateway() as gateway:
        first = subprocess.run(
            [sys.executable, "-m", "tasks.provider_worker", "--once"],
            cwd=Path(__file__).resolve().parent,
            env=_worker_environment(gateway.base_url, lease_seconds=2),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert first.returncode == 0, first.stderr
        failed_receipt = _provider_client().post(
            "/integration/gateway/v1/delivery-receipts",
            headers={"Authorization": f"Bearer {_GATEWAY_CREDENTIAL}"},
            json={
                "protocolVersion": "1.0",
                "receiptId": "receipt.attendance.worker.integration.1004",
                "provider": "ATTENDANCE",
                "actionId": action_id,
                "correlationId": action_id,
                "status": "PERMANENTLY_FAILED",
                "attemptedAt": "2026-08-09T10:00:01Z",
                "failure": {"code": "TELEGRAM_ERROR", "terminal": True},
            },
        )
        assert failed_receipt.status_code == 200, failed_receipt.text
        with psycopg2.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE attendance_worker_actions
                    SET next_attempt_at = clock_timestamp() - interval '1 second'
                    WHERE action_id = %s
                    """,
                    (action_id,),
                )
        second = subprocess.run(
            [sys.executable, "-m", "tasks.provider_worker", "--once"],
            cwd=Path(__file__).resolve().parent,
            env=_worker_environment(gateway.base_url, lease_seconds=2),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert second.returncode == 0, second.stderr

    assert len(gateway.requests) == 2
    successor = gateway.requests[1]
    successor_action_id = f"{action_id}.retry.2"
    assert successor["action"]["actionId"] == successor_action_id
    assert successor["correlationId"] == successor_action_id
    delivered_receipt = _provider_client().post(
        "/integration/gateway/v1/delivery-receipts",
        headers={"Authorization": f"Bearer {_GATEWAY_CREDENTIAL}"},
        json={
            "protocolVersion": "1.0",
            "receiptId": "receipt.attendance.worker.integration.1004.retry.2",
            "provider": "ATTENDANCE",
            "actionId": successor_action_id,
            "correlationId": successor_action_id,
            "status": "DELIVERED",
            "attemptedAt": "2026-08-09T10:00:03Z",
            "telegramResult": {
                "accepted": True,
                "messageId": 91004,
            },
        },
    )
    assert delivered_receipt.status_code == 200, delivered_receipt.text
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt_count, last_attempt_action_id
                FROM attendance_worker_actions
                WHERE action_id = %s
                """,
                (action_id,),
            )
            assert cursor.fetchone() == (
                "DELIVERED",
                2,
                successor_action_id,
            )


def test_acceptance_retry_uses_the_worker_cycle_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_database()
    action_id = "attendance.worker.integration.1005"
    _delete_worker_action(action_id)
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="notification:1005",
        request=_worker_request(action_id, text="接受失败退避测试"),
        max_attempts=3,
    )
    fixed_now = datetime(2099, 8, 9, 10, 0, tzinfo=timezone.utc)

    def reject_acceptance(
        _client: provider_worker.GatewayAsyncActionClient,
        _claim: worker_action_repo.ClaimedWorkerAction,
    ) -> None:
        raise provider_worker.GatewayActionAcceptanceError(
            "GATEWAY_HTTP_500",
            retryable=True,
        )

    monkeypatch.setattr(
        provider_worker.GatewayAsyncActionClient,
        "submit",
        reject_acceptance,
    )
    config = provider_worker.DurableProviderWorkerConfig(
        database_url=_database_url(),
        gateway_base_url="http://gateway.invalid",
        gateway_bearer_token=_ATTENDANCE_CREDENTIAL,
    )

    assert provider_worker.run_durable_worker_cycle(
        config,
        worker_id="worker-clock-test",
        now=fixed_now,
    ) == 1

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, updated_at, next_attempt_at
                FROM attendance_worker_actions
                WHERE action_id = %s
                """,
                (action_id,),
            )
            assert cursor.fetchone() == (
                "CLAIMED",
                fixed_now,
                fixed_now + timedelta(seconds=1),
            )


@pytest.mark.parametrize(
    "acceptance_payload",
    (
        {"invalid": True},
        {
            "protocolVersion": "1.0",
            "actionId": "attendance.worker.integration.other-action",
            "result": "ACCEPTED",
        },
    ),
)
def test_http_202_with_unverifiable_acceptance_is_uncertain_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
    acceptance_payload: dict[str, object],
) -> None:
    class Response:
        status_code = 202

        @staticmethod
        def json() -> dict[str, object]:
            return acceptance_payload

    monkeypatch.setattr(provider_worker.httpx, "post", lambda *_args, **_kwargs: Response())
    config = provider_worker.DurableProviderWorkerConfig(
        database_url="postgresql://unused",
        gateway_base_url="http://gateway.test",
        gateway_bearer_token=_ATTENDANCE_CREDENTIAL,
    )
    claim = worker_action_repo.ClaimedWorkerAction(
        root_action_id=_ROOT_ACTION_ID,
        attempt_action_id=_ROOT_ACTION_ID,
        request={
            "protocolVersion": "1.0",
            "provider": "ATTENDANCE",
            "correlationId": _ROOT_ACTION_ID,
            "createdAt": "2099-08-08T00:00:00Z",
            "action": {
                "actionId": _ROOT_ACTION_ID,
                "type": "SEND_GROUP_MESSAGE",
                "routeKey": "group-route.attendance.worker-test",
                "text": "durable acceptance",
            },
        },
        lease_owner="worker-test",
        attempt_number=1,
        acceptance_attempt_count=1,
    )

    with pytest.raises(provider_worker.GatewayActionAcceptanceError) as captured:
        provider_worker.GatewayAsyncActionClient(config).submit(claim)

    assert captured.value.retryable is True
    assert captured.value.uncertain is True


def test_dependent_actions_wait_for_predecessor_delivery() -> None:
    _prepare_database()
    first_action_id = "attendance.worker.integration.1010"
    second_action_id = "attendance.worker.integration.1011"
    first_request = _worker_request(first_action_id, text="先发送导出文件")
    second_request = _worker_request(second_action_id, text="再删除进度消息")
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="deferred-order:1010:1",
        request=first_request,
        max_attempts=3,
    )
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="deferred-order:1010:2",
        request=second_request,
        max_attempts=3,
        predecessor_action_id=first_action_id,
    )

    with _FakeGateway() as gateway:
        first = _run_worker_once(gateway.base_url)
        assert first.returncode == 0, first.stderr
        waiting = _run_worker_once(gateway.base_url)
        assert waiting.returncode == 0, waiting.stderr
        assert gateway.requests == [first_request]

        receipt = _provider_client().post(
            "/integration/gateway/v1/delivery-receipts",
            headers={"Authorization": f"Bearer {_GATEWAY_CREDENTIAL}"},
            json={
                "protocolVersion": "1.0",
                "receiptId": "receipt.attendance.worker.integration.1010",
                "provider": "ATTENDANCE",
                "actionId": first_action_id,
                "correlationId": first_action_id,
                "status": "DELIVERED",
                "attemptedAt": "2026-08-09T10:00:01Z",
                "telegramResult": {
                    "accepted": True,
                    "messageId": 91010,
                },
            },
        )
        assert receipt.status_code == 200, receipt.text

        second = _run_worker_once(gateway.base_url)
        assert second.returncode == 0, second.stderr
        assert gateway.requests == [first_request, second_request]


def test_terminal_predecessor_failure_supersedes_dependent_action() -> None:
    _prepare_database()
    first_action_id = "attendance.worker.integration.1012"
    second_action_id = "attendance.worker.integration.1013"
    first_request = _worker_request(first_action_id, text="会永久失败的文件")
    second_request = _worker_request(second_action_id, text="不得执行的清理")
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="deferred-order:1012:1",
        request=first_request,
        max_attempts=3,
    )
    worker_action_repo.enqueue_action(
        database_url=_database_url(),
        owner_key="deferred-order:1012:2",
        request=second_request,
        max_attempts=3,
        predecessor_action_id=first_action_id,
    )

    with _FakeGateway() as gateway:
        first = _run_worker_once(gateway.base_url)
        assert first.returncode == 0, first.stderr
        receipt = _provider_client().post(
            "/integration/gateway/v1/delivery-receipts",
            headers={"Authorization": f"Bearer {_GATEWAY_CREDENTIAL}"},
            json={
                "protocolVersion": "1.0",
                "receiptId": "receipt.attendance.worker.integration.1012",
                "provider": "ATTENDANCE",
                "actionId": first_action_id,
                "correlationId": first_action_id,
                "status": "PERMANENTLY_FAILED",
                "attemptedAt": "2026-08-09T10:00:01Z",
                "failure": {"code": "INVALID_ACTION", "terminal": True},
            },
        )
        assert receipt.status_code == 200, receipt.text
        reconciled = _run_worker_once(gateway.base_url)
        assert reconciled.returncode == 0, reconciled.stderr
        assert gateway.requests == [first_request]

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, last_error_code, terminal_at IS NOT NULL
                FROM attendance_worker_actions
                WHERE action_id = %s
                """,
                (second_action_id,),
            )
            assert cursor.fetchone() == (
                "UNDELIVERABLE",
                "PREDECESSOR_FAILED",
                True,
            )
