ALTER TABLE public.attendance_worker_actions
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(128),
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS last_attempt_action_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS last_receipt_id VARCHAR(128);

UPDATE public.attendance_worker_actions
SET next_attempt_at = COALESCE(next_attempt_at, created_at),
    updated_at = COALESCE(updated_at, created_at)
WHERE next_attempt_at IS NULL OR updated_at IS NULL;

ALTER TABLE public.attendance_worker_actions
    ALTER COLUMN next_attempt_at SET NOT NULL,
    ALTER COLUMN updated_at SET NOT NULL,
    DROP CONSTRAINT IF EXISTS attendance_worker_action_status;

ALTER TABLE public.attendance_worker_actions
    ADD CONSTRAINT attendance_worker_action_status CHECK (
        status IN (
            'PENDING', 'CLAIMED', 'SUBMITTED', 'DELIVERED',
            'RETRYING', 'UNDELIVERABLE', 'UNCERTAIN'
        )
    );

DO $$
BEGIN
    ALTER TABLE public.attendance_worker_actions
        ADD CONSTRAINT attendance_worker_action_max_attempts CHECK (
            max_attempts BETWEEN 1 AND 20
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE public.attendance_worker_actions
        ADD CONSTRAINT attendance_worker_action_lease_shape CHECK (
            status <> 'CLAIMED' OR lease_expires_at IS NOT NULL
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_worker_actions_owner
    ON public.attendance_worker_actions (action_kind, owner_key);

CREATE INDEX IF NOT EXISTS idx_attendance_worker_actions_due
    ON public.attendance_worker_actions (next_attempt_at, created_at)
    WHERE status IN ('PENDING', 'CLAIMED', 'RETRYING');

CREATE TABLE IF NOT EXISTS public.attendance_worker_action_attempts (
    attempt_action_id VARCHAR(128) PRIMARY KEY,
    root_action_id VARCHAR(128) NOT NULL
        REFERENCES public.attendance_worker_actions(action_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    correlation_id VARCHAR(256) NOT NULL UNIQUE,
    request_payload JSONB NOT NULL,
    status VARCHAR(24) NOT NULL,
    acceptance_attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    last_error_code VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    CONSTRAINT attendance_worker_attempt_identity_format CHECK (
        attempt_action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
        AND root_action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
        AND correlation_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]+$'
    ),
    CONSTRAINT attendance_worker_attempt_number_positive CHECK (
        attempt_number > 0 AND acceptance_attempt_count >= 0
    ),
    CONSTRAINT attendance_worker_attempt_status CHECK (
        status IN (
            'CLAIMED', 'ACCEPTANCE_RETRY', 'SUBMITTED',
            'DELIVERED', 'UNDELIVERABLE', 'UNCERTAIN'
        )
    ),
    CONSTRAINT attendance_worker_attempt_payload_object CHECK (
        jsonb_typeof(request_payload) = 'object'
    ),
    UNIQUE (root_action_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS idx_attendance_worker_attempts_root
    ON public.attendance_worker_action_attempts (root_action_id, attempt_number DESC);

CREATE TABLE IF NOT EXISTS public.attendance_worker_schedule_runs (
    run_key VARCHAR(256) PRIMARY KEY,
    job_kind VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    last_error_code VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT attendance_worker_schedule_status CHECK (
        status IN ('PROCESSING', 'RETRYING', 'COMPLETED')
    ),
    CONSTRAINT attendance_worker_schedule_lease_shape CHECK (
        status <> 'PROCESSING'
        OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
    ),
    CONSTRAINT attendance_worker_schedule_attempt_positive CHECK (
        attempt_count > 0
    )
);

CREATE INDEX IF NOT EXISTS idx_attendance_worker_schedule_due
    ON public.attendance_worker_schedule_runs (next_attempt_at, created_at)
    WHERE status IN ('PROCESSING', 'RETRYING');
