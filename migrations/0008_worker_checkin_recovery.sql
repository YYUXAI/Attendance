CREATE TABLE IF NOT EXISTS public.attendance_worker_actions (
    action_id VARCHAR(128) PRIMARY KEY,
    correlation_id VARCHAR(256) NOT NULL UNIQUE,
    action_kind VARCHAR(64) NOT NULL,
    owner_key VARCHAR(256) NOT NULL,
    action_payload JSONB NOT NULL,
    status VARCHAR(24) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error_code VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    CONSTRAINT attendance_worker_action_id_format CHECK (
        action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
    ),
    CONSTRAINT attendance_worker_action_status CHECK (
        status IN (
            'PENDING', 'SUBMITTED', 'DELIVERED',
            'RETRYING', 'UNDELIVERABLE', 'UNCERTAIN'
        )
    ),
    CONSTRAINT attendance_worker_action_payload_object CHECK (
        jsonb_typeof(action_payload) = 'object'
    )
);

CREATE TABLE IF NOT EXISTS public.attendance_daily_report_ledger (
    report_date DATE PRIMARY KEY,
    action_id VARCHAR(128) NOT NULL UNIQUE,
    delivered_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attendance_worker_actions_status
    ON public.attendance_worker_actions (status, created_at);
