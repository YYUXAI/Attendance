ALTER TABLE public.attendance_worker_schedule_runs
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS lease_version BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.attendance_worker_schedule_runs
    DROP CONSTRAINT IF EXISTS attendance_worker_schedule_status,
    DROP CONSTRAINT IF EXISTS attendance_worker_schedule_attempt_positive,
    DROP CONSTRAINT IF EXISTS attendance_worker_schedule_attempt_nonnegative,
    DROP CONSTRAINT IF EXISTS attendance_worker_schedule_lease_version_nonnegative,
    DROP CONSTRAINT IF EXISTS attendance_worker_schedule_payload_object;

ALTER TABLE public.attendance_worker_schedule_runs
    ADD CONSTRAINT attendance_worker_schedule_status CHECK (
        status IN ('PENDING', 'PROCESSING', 'RETRYING', 'COMPLETED')
    ),
    ADD CONSTRAINT attendance_worker_schedule_attempt_nonnegative CHECK (
        attempt_count >= 0
    ),
    ADD CONSTRAINT attendance_worker_schedule_lease_version_nonnegative CHECK (
        lease_version >= 0
    ),
    ADD CONSTRAINT attendance_worker_schedule_payload_object CHECK (
        jsonb_typeof(payload) = 'object'
    );

CREATE INDEX IF NOT EXISTS idx_attendance_worker_schedule_kind_due
    ON public.attendance_worker_schedule_runs (
        job_kind, next_attempt_at, created_at, run_key
    )
    WHERE status IN ('PENDING', 'PROCESSING', 'RETRYING');
