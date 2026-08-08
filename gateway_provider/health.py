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
    business_truth = False
    webapp_sessions = False
    try:
        with psycopg2.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        to_regclass('public.gateway_processed_events')
                            IS NOT NULL,
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
                business_truth = bool(row and row[1])
                webapp_sessions = bool(row and row[2])
    except psycopg2.Error:
        return _readiness_result(False, False, False, False)
    return _readiness_result(
        database,
        processed_events,
        business_truth,
        webapp_sessions,
    )


def _readiness_result(
    database: bool,
    processed_events: bool,
    business_truth: bool,
    webapp_sessions: bool,
) -> dict[str, object]:
    ready = database and processed_events and business_truth and webapp_sessions
    return {
        "ok": ready,
        "status": "READY" if ready else "NOT_READY",
        "database": database,
        "requiredTables": {
            "gatewayProcessedEvents": processed_events,
            "businessTruth": business_truth,
            "webappSessions": webapp_sessions,
        },
    }
