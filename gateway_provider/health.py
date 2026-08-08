from __future__ import annotations

import psycopg2


def check_database_liveness(database_url: str) -> bool:
    try:
        with psycopg2.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except psycopg2.Error:
        return False


def read_provider_readiness(database_url: str) -> dict[str, object]:
    database = False
    processed_events = False
    delivery_receipts = False
    business_truth = False
    webapp_sessions = False
    permanent_delivery_failures: int | None = None
    uncertain_deliveries: int | None = None
    try:
        with psycopg2.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        to_regclass('public.gateway_processed_events')
                            IS NOT NULL,
                        to_regclass(
                            'public.attendance_gateway_delivery_receipts'
                        ) IS NOT NULL,
                        to_regclass('public.registrations') IS NOT NULL
                            AND to_regclass(
                                'public.attendance_registration_sessions'
                            ) IS NOT NULL
                            AND to_regclass('public.clock_records') IS NOT NULL
                            AND to_regclass(
                                'public.employee_shift_roster'
                            ) IS NOT NULL,
                        to_regclass('public.attendance_webapp_sessions')
                            IS NOT NULL
                    """
                )
                row = cursor.fetchone()
                database = True
                processed_events = bool(row and row[0])
                delivery_receipts = bool(row and row[1])
                business_truth = bool(row and row[2])
                webapp_sessions = bool(row and row[3])
                if delivery_receipts:
                    cursor.execute(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE status = 'PERMANENTLY_FAILED'
                            ),
                            count(*) FILTER (WHERE status = 'UNCERTAIN')
                        FROM attendance_gateway_delivery_receipts
                        """
                    )
                    operational = cursor.fetchone()
                    permanent_delivery_failures = int(operational[0])
                    uncertain_deliveries = int(operational[1])
    except psycopg2.Error:
        return _readiness_result(
            False,
            False,
            False,
            False,
            False,
            None,
            None,
        )
    return _readiness_result(
        database,
        processed_events,
        delivery_receipts,
        business_truth,
        webapp_sessions,
        permanent_delivery_failures,
        uncertain_deliveries,
    )


def _readiness_result(
    database: bool,
    processed_events: bool,
    delivery_receipts: bool,
    business_truth: bool,
    webapp_sessions: bool,
    permanent_delivery_failures: int | None,
    uncertain_deliveries: int | None,
) -> dict[str, object]:
    ready = (
        database
        and processed_events
        and delivery_receipts
        and business_truth
        and webapp_sessions
        and permanent_delivery_failures == 0
        and uncertain_deliveries == 0
    )
    return {
        "ok": ready,
        "status": "READY" if ready else "NOT_READY",
        "database": database,
        "requiredTables": {
            "gatewayProcessedEvents": processed_events,
            "deliveryReceipts": delivery_receipts,
            "businessTruth": business_truth,
            "webappSessions": webapp_sessions,
        },
        "operational": {
            "permanentDeliveryFailures": permanent_delivery_failures,
            "uncertainDeliveries": uncertain_deliveries,
        },
    }
