from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from gateway_provider.contracts import (
    GatewayDeliveryReceiptRequest,
    GatewayEventRequest,
    event_response_value,
)
from gateway_provider.event_module import (
    AttendanceGatewayEventModule,
    GatewayEventIdConflictError,
    GatewayRouteOwnershipMismatchError,
)
from gateway_provider.gateway_file_client import GatewayFileReader
from gateway_provider.health import (
    check_database_liveness,
    read_provider_readiness,
)
from gateway_provider.receipt_module import (
    AttendanceGatewayReceiptModule,
    GatewayReceiptActionNotFoundError,
    GatewayReceiptIdConflictError,
)
from gateway_provider.summary_module import read_attendance_summary


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AttendanceGatewayProviderConfig:
    database_url: str
    gateway_to_attendance_bearer_token: str
    gateway_internal_base_url: str
    attendance_to_gateway_bearer_token: str

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("database_url is required")
        if len(self.gateway_to_attendance_bearer_token) < 32:
            raise ValueError(
                "gateway_to_attendance_bearer_token must contain at least 32 characters"
            )
        if self.gateway_to_attendance_bearer_token == (
            self.attendance_to_gateway_bearer_token
        ):
            raise ValueError("Gateway credentials must be direction-specific")


def create_attendance_gateway_provider_app(
    config: AttendanceGatewayProviderConfig,
) -> FastAPI:
    event_module = AttendanceGatewayEventModule(
        config.database_url,
        GatewayFileReader(
            base_url=config.gateway_internal_base_url,
            bearer_token=config.attendance_to_gateway_bearer_token,
        ),
    )
    receipt_module = AttendanceGatewayReceiptModule(config.database_url)
    app = FastAPI(title="Attendance Gateway Provider", version="1.0.0")

    @app.get("/healthz")
    async def health() -> JSONResponse:
        healthy = await run_in_threadpool(
            check_database_liveness,
            config.database_url,
        )
        return JSONResponse(
            {"ok": healthy, "status": "HEALTHY" if healthy else "UNHEALTHY"},
            status_code=200 if healthy else 503,
        )

    @app.get("/readyz")
    async def readiness() -> JSONResponse:
        result = await run_in_threadpool(
            read_provider_readiness,
            config.database_url,
        )
        return JSONResponse(result, status_code=200 if result["ok"] else 503)

    @app.post("/integration/gateway/v1/events")
    async def process_gateway_event(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if not _bearer_token_matches(
            authorization,
            expected=config.gateway_to_attendance_bearer_token,
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

    @app.post("/integration/gateway/v1/delivery-receipts")
    async def process_gateway_delivery_receipt(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if not _bearer_token_matches(
            authorization,
            expected=config.gateway_to_attendance_bearer_token,
        ):
            return _error_response(
                status_code=401,
                code="UNAUTHORIZED",
                message="Gateway 凭据无效。",
            )
        try:
            raw_receipt = await request.json()
            receipt = GatewayDeliveryReceiptRequest.model_validate(
                raw_receipt,
                strict=True,
            )
        except (ValueError, ValidationError) as error:
            return _validation_error_response(error)
        try:
            result = await run_in_threadpool(
                receipt_module.process_receipt,
                receipt,
            )
        except GatewayReceiptIdConflictError:
            return _error_response(
                status_code=409,
                code="RECEIPT_ID_CONFLICT",
                message="receiptId 已绑定到不同终态。",
            )
        except GatewayReceiptActionNotFoundError:
            return _error_response(
                status_code=404,
                code="ACTION_NOT_FOUND",
                message="Attendance 不拥有该 Gateway action。",
            )
        except Exception as error:
            logger.error(
                "Attendance Gateway receipt processing failed",
                extra={"error_type": type(error).__name__},
            )
            return _error_response(
                status_code=500,
                code="INTERNAL_ERROR",
                message="Attendance 回执处理失败。",
            )
        return JSONResponse(
            {
                "protocolVersion": "1.0",
                "receiptId": receipt.receiptId,
                "result": result,
            },
            status_code=200,
        )

    @app.get("/integration/gateway/v1/attendance-summary")
    async def read_gateway_attendance_summary(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if not _bearer_token_matches(
            authorization,
            expected=config.gateway_to_attendance_bearer_token,
        ):
            return _error_response(
                status_code=401,
                code="UNAUTHORIZED",
                message="Gateway 凭据无效。",
            )
        telegram_user_id = _telegram_user_id(request)
        if telegram_user_id is None:
            return _error_response(
                status_code=400,
                code="INVALID_QUERY",
                message="telegramUserId 必须是 int64 整数。",
            )
        try:
            summary = await run_in_threadpool(
                read_attendance_summary,
                database_url=config.database_url,
                telegram_user_id=telegram_user_id,
            )
        except Exception as error:
            logger.error(
                "Attendance summary read failed",
                extra={"error_type": type(error).__name__},
            )
            return _error_response(
                status_code=500,
                code="INTERNAL_ERROR",
                message="Attendance 摘要读取失败。",
            )
        return JSONResponse(summary.model_dump(mode="json"), status_code=200)

    return app


def _bearer_token_matches(header: str | None, *, expected: str) -> bool:
    if header is None or not header.startswith("Bearer "):
        return False
    supplied = header.removeprefix("Bearer ")
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _telegram_user_id(request: Request) -> int | None:
    values = request.query_params.getlist("telegramUserId")
    if len(values) != 1:
        return None
    raw_value = values[0]
    digits = raw_value.removeprefix("-")
    if not digits or any(character < "0" or character > "9" for character in digits):
        return None
    value = int(raw_value)
    if value < -(2**63) or value > 2**63 - 1:
        return None
    return value


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
