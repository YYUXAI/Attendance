ALTER TABLE public.attendance_worker_actions
    ADD COLUMN IF NOT EXISTS predecessor_action_id VARCHAR(128);

DO $$
BEGIN
    ALTER TABLE public.attendance_worker_actions
        ADD CONSTRAINT attendance_worker_action_predecessor_fk
        FOREIGN KEY (predecessor_action_id)
        REFERENCES public.attendance_worker_actions(action_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE public.attendance_worker_actions
        ADD CONSTRAINT attendance_worker_action_predecessor_distinct CHECK (
            predecessor_action_id IS NULL OR predecessor_action_id <> action_id
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_attendance_worker_actions_predecessor
    ON public.attendance_worker_actions (predecessor_action_id)
    WHERE predecessor_action_id IS NOT NULL;

ALTER TABLE public.attendance_worker_schedule_runs
    DROP CONSTRAINT IF EXISTS attendance_worker_schedule_status;

ALTER TABLE public.attendance_worker_schedule_runs
    ADD CONSTRAINT attendance_worker_schedule_status CHECK (
        status IN ('PENDING', 'PROCESSING', 'RETRYING', 'COMPLETED', 'FAILED')
    );
