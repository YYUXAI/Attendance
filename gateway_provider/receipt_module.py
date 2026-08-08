from __future__ import annotations

import hashlib
import json

import psycopg2
from psycopg2.extras import Json

from gateway_provider.contracts import GatewayDeliveryReceiptRequest


class GatewayReceiptIdConflictError(RuntimeError):
    pass


class GatewayReceiptActionNotFoundError(RuntimeError):
    pass


class AttendanceGatewayReceiptModule:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def process_receipt(
        self,
        receipt: GatewayDeliveryReceiptRequest,
    ) -> str:
        payload = receipt.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        request_hash = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (receipt.receiptId,),
                )
                cursor.execute(
                    """
                    SELECT request_hash
                    FROM attendance_gateway_delivery_receipts
                    WHERE receipt_id = %s
                    """,
                    (receipt.receiptId,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    if existing[0] != request_hash:
                        raise GatewayReceiptIdConflictError()
                    return "DUPLICATE"

                if receipt.relatedEventId is None:
                    raise GatewayReceiptActionNotFoundError()
                cursor.execute(
                    """
                    SELECT 1
                    FROM gateway_processed_events AS event
                    WHERE event.event_id = %s
                      AND EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements(
                              event.response_json->'actions'
                          ) AS action
                          WHERE action->>'actionId' = %s
                      )
                    """,
                    (receipt.relatedEventId, receipt.actionId),
                )
                if cursor.fetchone() is None:
                    raise GatewayReceiptActionNotFoundError()

                cursor.execute(
                    """
                    INSERT INTO attendance_gateway_delivery_receipts (
                        receipt_id,
                        action_id,
                        related_event_id,
                        correlation_id,
                        request_hash,
                        status,
                        receipt_payload,
                        processed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, clock_timestamp())
                    """,
                    (
                        receipt.receiptId,
                        receipt.actionId,
                        receipt.relatedEventId,
                        receipt.correlationId,
                        request_hash,
                        receipt.status,
                        Json(payload),
                    ),
                )
                return "PROCESSED"
