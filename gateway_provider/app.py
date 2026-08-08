from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from gateway_provider.contracts import (
    GatewayEventRequest,
    event_response_value,
)
from gateway_provider.event_module import (
    AttendanceGatewayEventModule,
    GatewayEventIdConflictError,
    GatewayRouteOwnershipMismatchError,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AttendanceGatewayProviderConfig:
    database_url: str
    gateway_bearer_token: str

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("database_url is required")
        if len(self.gateway_bearer_token) < 32:
            raise ValueError("gateway_bearer_token must contain at least 32 characters")


def create_attendance_gateway_provider_app(
    config: AttendanceGatewayProviderConfig,
) -> FastAPI:
    event_module = AttendanceGatewayEventModule(config.database_url)
    app = FastAPI(title="Attendance Gateway Provider", version="1.0.0")

    @app.post("/integration/gateway/v1/events")
    async def process_gateway_event(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if not _bearer_token_matches(
            authorization,
            expected=config.gateway_bearer_token,
        ):
            return _error_response(
                status_code=401,
                code="UNAUTHORIZED",
                message="Gateway 凭据无效。",
            )
        try:
            raw_event = await request.json()
            event = GatewayEventRequest.model_validate(raw_event, strict=True)
        except (ValueError, ValidationError) as error:
            return _validation_error_response(error)
        try:
            response = await run_in_threadpool(event_module.process_event, event)
        except GatewayEventIdConflictError as error:
            return _error_response(
                status_code=409,
                code="EVENT_ID_CONFLICT",
                message="eventId 已绑定到不同请求。",
                details={"provider": "ATTENDANCE", "eventId": error.event_id},
            )
        except GatewayRouteOwnershipMismatchError:
            return _error_response(
                status_code=409,
                code="ROUTE_OWNERSHIP_MISMATCH",
                message="事件不属于 Attendance 路由。",
                details={"provider": "ATTENDANCE", "eventId": event.eventId},
            )
        except Exception as error:
            logger.error(
                "Attendance Gateway event processing failed",
                extra={"error_type": type(error).__name__},
            )
            return _error_response(
                status_code=500,
                code="INTERNAL_ERROR",
                message="Attendance 处理失败。",
                details={"provider": "ATTENDANCE", "eventId": event.eventId},
            )
        return JSONResponse(event_response_value(response), status_code=200)

    return app


def _bearer_token_matches(header: str | None, *, expected: str) -> bool:
    if header is None or not header.startswith("Bearer "):
        return False
    supplied = header.removeprefix("Bearer ")
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse({"error": error}, status_code=status_code)


def _validation_error_response(error: ValueError) -> JSONResponse:
    issues = []
    if isinstance(error, ValidationError):
        issues = [
            {
                "path": ".".join(str(part) for part in issue["loc"]),
                "code": _validation_issue_code(issue["type"]),
            }
            for issue in error.errors()[:100]
        ]
    return _error_response(
        status_code=422,
        code="INVALID_REQUEST",
        message="请求不符合 Gateway V1 协议。",
        details={"issues": issues},
    )


def _validation_issue_code(issue_type: str) -> str:
    if issue_type == "missing":
        return "REQUIRED"
    if issue_type == "extra_forbidden":
        return "UNKNOWN_FIELD"
    if issue_type.startswith("literal"):
        return "ENUM"
    if issue_type.startswith(("greater_than", "less_than", "string_too")):
        return "RANGE"
    return "TYPE"
