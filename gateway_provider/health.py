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
    worker_actions = False
    worker_schedules = False
    permanent_delivery_failures: int | None = None
    uncertain_deliveries: int | None = None
    worker_permanent_failures: int | None = None
    worker_uncertain: int | None = None
    worker_pending: int | None = None
    worker_acceptance_retry: int | None = None
    worker_expired_leases: int | None = None
    worker_stale_backlog: int | None = None
    scheduler_retrying: int | None = None
    scheduler_failed: int | None = None
    scheduler_expired_leases: int | None = None
    scheduler_stale_backlog: int | None = None
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
                            IS NOT NULL,
                        to_regclass('public.attendance_worker_actions')
                            IS NOT NULL
                            AND to_regclass(
                                'public.attendance_worker_action_attempts'
                            ) IS NOT NULL,
                        to_regclass(
                            'public.attendance_worker_schedule_runs'
                        ) IS NOT NULL
                    """
                )
                row = cursor.fetchone()
                database = True
                processed_events = bool(row and row[0])
                delivery_receipts = bool(row and row[1])
                business_truth = bool(row and row[2])
                webapp_sessions = bool(row and row[3])
                worker_actions = bool(row and row[4])
                worker_schedules = bool(row and row[5])
                if delivery_receipts:
                    cursor.execute(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE status = 'PERMANENTLY_FAILED'
                            ),
                            count(*) FILTER (WHERE status = 'UNCERTAIN')
                        FROM attendance_gateway_delivery_receipts AS receipt
                        LEFT JOIN attendance_operational_incident_acknowledgements AS acknowledgement
                          ON acknowledgement.incident_kind = 'delivery-receipt'
                         AND acknowledgement.incident_id = receipt.receipt_id
                        WHERE acknowledgement.incident_id IS NULL
                        """
                    )
                    operational = cursor.fetchone()
                    permanent_delivery_failures = int(operational[0])
                    uncertain_deliveries = int(operational[1])
                if worker_actions:
                    cursor.execute(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE status = 'UNDELIVERABLE'
                            ),
                            count(*) FILTER (WHERE status = 'UNCERTAIN'),
                            count(*) FILTER (
                                WHERE status IN ('PENDING', 'RETRYING')
                            ),
                            count(*) FILTER (
                                WHERE status = 'CLAIMED'
                                  AND lease_expires_at <= clock_timestamp()
                            ),
                            count(*) FILTER (
                                WHERE status IN ('PENDING', 'RETRYING')
                                  AND next_attempt_at <= (
                                      clock_timestamp() - interval '5 minutes'
                                  )
                            )
                        FROM attendance_worker_actions AS action
                        LEFT JOIN attendance_operational_incident_acknowledgements AS acknowledgement
                          ON acknowledgement.incident_kind = 'worker-action'
                         AND acknowledgement.incident_id = action.action_id
                        WHERE acknowledgement.incident_id IS NULL
                        """
                    )
                    worker_operational = cursor.fetchone()
                    worker_permanent_failures = int(worker_operational[0])
                    worker_uncertain = int(worker_operational[1])
                    worker_pending = int(worker_operational[2])
                    worker_expired_leases = int(worker_operational[3])
                    worker_stale_backlog = int(worker_operational[4])
                    cursor.execute(
                        """
                        SELECT count(*)
                        FROM attendance_worker_action_attempts
                        WHERE status = 'ACCEPTANCE_RETRY'
                        """
                    )
                    worker_acceptance_retry = int(cursor.fetchone()[0])
                if worker_schedules:
                    cursor.execute(
                        """
                        SELECT
                            count(*) FILTER (WHERE status = 'RETRYING'),
                            count(*) FILTER (WHERE status = 'FAILED'),
                            count(*) FILTER (
                                WHERE status = 'PROCESSING'
                                  AND lease_expires_at <= clock_timestamp()
                            ),
                            count(*) FILTER (
                                WHERE status IN ('PENDING', 'RETRYING')
                                  AND next_attempt_at <= (
                                      clock_timestamp() - interval '5 minutes'
                                  )
                            )
                        FROM attendance_worker_schedule_runs AS schedule
                        LEFT JOIN attendance_operational_incident_acknowledgements AS acknowledgement
                          ON acknowledgement.incident_kind = 'schedule-run'
                         AND acknowledgement.incident_id = schedule.run_key
                        WHERE acknowledgement.incident_id IS NULL
                        """
                    )
                    schedule_operational = cursor.fetchone()
                    scheduler_retrying = int(schedule_operational[0])
                    scheduler_failed = int(schedule_operational[1])
                    scheduler_expired_leases = int(schedule_operational[2])
                    scheduler_stale_backlog = int(schedule_operational[3])
    except psycopg2.Error:
        return _readiness_result(
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    return _readiness_result(
        database,
        processed_events,
        delivery_receipts,
        business_truth,
        webapp_sessions,
        worker_actions,
        worker_schedules,
        permanent_delivery_failures,
        uncertain_deliveries,
        worker_permanent_failures,
        worker_uncertain,
        worker_pending,
        worker_acceptance_retry,
        worker_expired_leases,
        worker_stale_backlog,
        scheduler_retrying,
        scheduler_failed,
        scheduler_expired_leases,
        scheduler_stale_backlog,
    )


def _readiness_result(
    database: bool,
    processed_events: bool,
    delivery_receipts: bool,
    business_truth: bool,
    webapp_sessions: bool,
    worker_actions: bool,
    worker_schedules: bool,
    permanent_delivery_failures: int | None,
    uncertain_deliveries: int | None,
    worker_permanent_failures: int | None,
    worker_uncertain: int | None,
    worker_pending: int | None,
    worker_acceptance_retry: int | None,
    worker_expired_leases: int | None,
    worker_stale_backlog: int | None,
    scheduler_retrying: int | None,
    scheduler_failed: int | None,
    scheduler_expired_leases: int | None,
    scheduler_stale_backlog: int | None,
) -> dict[str, object]:
    ready = (
        database
        and processed_events
        and delivery_receipts
        and business_truth
        and webapp_sessions
        and worker_actions
        and worker_schedules
        and permanent_delivery_failures == 0
        and uncertain_deliveries == 0
        and worker_permanent_failures == 0
        and worker_uncertain == 0
        and worker_expired_leases == 0
        and worker_stale_backlog == 0
        and scheduler_failed == 0
        and scheduler_expired_leases == 0
        and scheduler_stale_backlog == 0
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
            "workerActions": worker_actions,
            "workerSchedules": worker_schedules,
        },
        "operational": {
            "permanentDeliveryFailures": permanent_delivery_failures,
            "uncertainDeliveries": uncertain_deliveries,
            "workerPermanentFailures": worker_permanent_failures,
            "workerUncertain": worker_uncertain,
            "workerPending": worker_pending,
            "workerAcceptanceRetry": worker_acceptance_retry,
            "workerExpiredLeases": worker_expired_leases,
            "workerStaleBacklog": worker_stale_backlog,
            "schedulerRetrying": scheduler_retrying,
            "schedulerFailed": scheduler_failed,
            "schedulerExpiredLeases": scheduler_expired_leases,
            "schedulerStaleBacklog": scheduler_stale_backlog,
        },
    }
