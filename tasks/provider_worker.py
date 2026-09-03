from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from typing import Sequence
from urllib.parse import urlsplit

import httpx

from gateway_provider.contracts import GatewayAsyncActionAcceptanceResponse
from gateway_provider.runtime_security import assert_no_telegram_owner_credentials
from infra.runtime_config_validation import validate_attendance_process_environment
from infra.logger import configure_logging
from repositories import runtime_component_repo, worker_action_repo


log = logging.getLogger(__name__)

@dataclass(frozen=True)
class DurableProviderWorkerConfig:
    database_url: str
    gateway_base_url: str
    gateway_bearer_token: str
    poll_interval_seconds: float = 2.0
    lease_seconds: int = 30
    batch_size: int = 20
    acceptance_timeout_seconds: float = 10.0
    maximum_acceptance_attempts: int = 8

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("database_url is required")
        parsed = urlsplit(self.gateway_base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("gateway_base_url must be an HTTP(S) base URL")
        if len(self.gateway_bearer_token) < 32:
            raise ValueError("gateway_bearer_token must contain at least 32 characters")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.lease_seconds < 1 or self.lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        if self.batch_size < 1 or self.batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        if self.acceptance_timeout_seconds <= 0:
            raise ValueError("acceptance_timeout_seconds must be positive")
        if self.maximum_acceptance_attempts < 1:
            raise ValueError("maximum_acceptance_attempts must be positive")


class GatewayActionAcceptanceError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool, uncertain: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.uncertain = uncertain


class GatewayAsyncActionClient:
    def __init__(self, config: DurableProviderWorkerConfig) -> None:
        self._url = f"{config.gateway_base_url.rstrip('/')}/internal/v1/actions"
        self._bearer_token = config.gateway_bearer_token
        self._timeout = config.acceptance_timeout_seconds

    def submit(self, claim: worker_action_repo.ClaimedWorkerAction) -> None:
        try:
            response = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._bearer_token}"},
                json=claim.request,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as error:
            raise GatewayActionAcceptanceError(
                "GATEWAY_TIMEOUT",
                retryable=True,
                uncertain=True,
            ) from error
        except httpx.HTTPError as error:
            raise GatewayActionAcceptanceError(
                f"GATEWAY_{type(error).__name__.upper()}",
                retryable=True,
            ) from error
        if response.status_code == 202:
            try:
                accepted = GatewayAsyncActionAcceptanceResponse.model_validate(
                    response.json(),
                    strict=True,
                )
            except Exception as error:
                raise GatewayActionAcceptanceError(
                    "GATEWAY_INVALID_ACCEPTANCE_RESPONSE",
                    retryable=True,
                    uncertain=True,
                ) from error
            if accepted.actionId != claim.attempt_action_id:
                raise GatewayActionAcceptanceError(
                    "GATEWAY_ACTION_ID_MISMATCH",
                    retryable=True,
                    uncertain=True,
                )
            return
        if response.status_code == 429 or response.status_code >= 500:
            raise GatewayActionAcceptanceError(
                f"GATEWAY_HTTP_{response.status_code}",
                retryable=True,
            )
        raise GatewayActionAcceptanceError(
            f"GATEWAY_HTTP_{response.status_code}",
            retryable=False,
        )


def run_durable_worker_cycle(
    config: DurableProviderWorkerConfig,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(timezone.utc)
    claims = worker_action_repo.claim_due_actions(
        database_url=config.database_url,
        worker_id=worker_id,
        now=current,
        lease_seconds=config.lease_seconds,
        limit=config.batch_size,
    )
    gateway = GatewayAsyncActionClient(config)
    for claim in claims:
        try:
            gateway.submit(claim)
        except GatewayActionAcceptanceError as error:
            if error.retryable:
                worker_action_repo.mark_acceptance_retry(
                    database_url=config.database_url,
                    claim=claim,
                    error_code=error.code,
                    now=current,
                    retry_seconds=_acceptance_retry_seconds(
                        claim.acceptance_attempt_count
                    ),
                    maximum_acceptance_attempts=(
                        config.maximum_acceptance_attempts
                    ),
                )
            else:
                worker_action_repo.mark_acceptance_terminal(
                    database_url=config.database_url,
                    claim=claim,
                    error_code=error.code,
                    now=current,
                    uncertain=error.uncertain,
                )
            continue
        worker_action_repo.mark_submitted(
            database_url=config.database_url,
            claim=claim,
            submitted_at=current,
        )
    return len(claims)


def run_durable_worker_loop(
    config: DurableProviderWorkerConfig,
    *,
    worker_id: str,
    stop_event: Event | None = None,
    public_config_fingerprint: str | None = None,
) -> None:
    stopped = stop_event or Event()
    while not stopped.is_set():
        try:
            if public_config_fingerprint is not None:
                runtime_component_repo.record_runtime_component(
                    database_url=config.database_url,
                    component="worker",
                    public_config_fingerprint=public_config_fingerprint,
                )
            run_durable_worker_cycle(config, worker_id=worker_id)
        except Exception:
            log.exception("attendance provider worker cycle failed")
        stopped.wait(config.poll_interval_seconds)


def load_durable_worker_config(environment: dict[str, str]) -> DurableProviderWorkerConfig:
    enabled = (environment.get("ATTENDANCE_PROVIDER_WORKER_ENABLED") or "").strip()
    if enabled.lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("ATTENDANCE_PROVIDER_WORKER_ENABLED=true is required")
    return DurableProviderWorkerConfig(
        database_url=_required_environment(
            environment,
            "ATTENDANCE_DATABASE_URL",
        ),
        gateway_base_url=_required_environment(
            environment,
            "GATEWAY_INTERNAL_BASE_URL",
        ),
        gateway_bearer_token=_required_environment(
            environment,
            "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN",
        ),
        poll_interval_seconds=float(
            environment.get("ATTENDANCE_PROVIDER_WORKER_POLL_SECONDS") or "2"
        ),
        lease_seconds=int(
            environment.get("ATTENDANCE_PROVIDER_WORKER_LEASE_SECONDS") or "30"
        ),
        batch_size=int(
            environment.get("ATTENDANCE_PROVIDER_WORKER_BATCH_SIZE") or "20"
        ),
        acceptance_timeout_seconds=float(
            environment.get("ATTENDANCE_PROVIDER_WORKER_TIMEOUT_SECONDS") or "10"
        ),
        maximum_acceptance_attempts=int(
            environment.get("ATTENDANCE_PROVIDER_WORKER_MAX_ACCEPTANCE_ATTEMPTS")
            or "8"
        ),
    )


def main(arguments: Sequence[str] | None = None) -> int:
    configure_logging()
    assert_no_telegram_owner_credentials(os.environ)
    validate_attendance_process_environment("worker", os.environ)
    args = list(arguments if arguments is not None else sys.argv[1:])
    if args not in ([], ["--once"]):
        raise RuntimeError("usage: python -m tasks.provider_worker [--once]")
    config = load_durable_worker_config(dict(os.environ))
    worker_action_repo.assert_schema_ready(database_url=config.database_url)
    public_config_fingerprint = _required_environment(
        dict(os.environ), "ATTENDANCE_PUBLIC_CONFIG_FINGERPRINT"
    )
    runtime_component_repo.record_runtime_component(
        database_url=config.database_url,
        component="worker",
        public_config_fingerprint=public_config_fingerprint,
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    if args == ["--once"]:
        run_durable_worker_cycle(config, worker_id=worker_id)
        return 0
    stopped = Event()
    signal.signal(signal.SIGINT, lambda *_args: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_args: stopped.set())
    run_durable_worker_loop(
        config,
        worker_id=worker_id,
        stop_event=stopped,
        public_config_fingerprint=public_config_fingerprint,
    )
    return 0


def _required_environment(environment: dict[str, str], name: str) -> str:
    value = (environment.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _acceptance_retry_seconds(acceptance_attempt_count: int) -> int:
    return min(60, 2 ** max(0, acceptance_attempt_count - 1))


if __name__ == "__main__":
    raise SystemExit(main())
