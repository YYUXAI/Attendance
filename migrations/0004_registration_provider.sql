DROP TABLE IF EXISTS public.attendance_telegram_update_inbox;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'attendance_registration_sessions'
          AND column_name = 'bot_owner'
    ) THEN
        DROP TABLE public.attendance_registration_sessions;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.attendance_registration_sessions (
    tg_id BIGINT PRIMARY KEY,
    private_chat_id BIGINT NOT NULL,
    stage TEXT NOT NULL,
    english_name TEXT,
    employee_id TEXT,
    preview_token_hash CHAR(64),
    created_at TIMESTAMPTZ NOT NULL,
    last_activity_at TIMESTAMPTZ NOT NULL,
    inactivity_expires_at TIMESTAMPTZ NOT NULL,
    absolute_expires_at TIMESTAMPTZ NOT NULL,
    preview_expires_at TIMESTAMPTZ,
    CONSTRAINT attendance_registration_sessions_stage_check
        CHECK (stage IN ('awaiting_input', 'awaiting_confirmation')),
    CONSTRAINT attendance_registration_sessions_preview_shape_check
        CHECK (
            (stage = 'awaiting_input'
                AND english_name IS NULL
                AND employee_id IS NULL
                AND preview_token_hash IS NULL
                AND preview_expires_at IS NULL)
            OR
            (stage = 'awaiting_confirmation'
                AND english_name IS NOT NULL
                AND employee_id IS NOT NULL
                AND preview_token_hash IS NOT NULL
                AND preview_expires_at IS NOT NULL)
        ),
    CONSTRAINT attendance_registration_sessions_expiry_check
        CHECK (
            created_at <= last_activity_at
            AND last_activity_at <= inactivity_expires_at
            AND inactivity_expires_at <= absolute_expires_at
            AND (preview_expires_at IS NULL OR preview_expires_at <= absolute_expires_at)
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_registration_preview_token
    ON public.attendance_registration_sessions (preview_token_hash)
    WHERE preview_token_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_attendance_registration_sessions_expiry
    ON public.attendance_registration_sessions (
        LEAST(inactivity_expires_at, absolute_expires_at)
    );

CREATE TABLE IF NOT EXISTS public.registrations (
    id BIGSERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL UNIQUE,
    tg_id BIGINT UNIQUE,
    english_name TEXT,
    tg_username TEXT,
    registered_at TIMESTAMPTZ,
    registered_chat_id BIGINT,
    organization_id BIGINT,
    shift_id BIGINT
);

CREATE TABLE IF NOT EXISTS public.organizations (
    id BIGSERIAL PRIMARY KEY,
    department_name TEXT,
    leader_employee_id TEXT,
    highest_responsible_employee_id TEXT
);

CREATE TABLE IF NOT EXISTS public.shifts (
    id BIGSERIAL PRIMARY KEY,
    checkin_time TIME,
    checkout_time TIME,
    timezone TEXT,
    is_overnight BOOLEAN NOT NULL DEFAULT FALSE,
    attendance_group_id BIGINT,
    attendance_flex_interval INTERVAL,
    max_late_early_tolerance INTERVAL,
    qc_enabled BOOLEAN,
    qc_trigger_interval INTERVAL,
    qc_draw_count INTEGER,
    qc_example_file_id TEXT
);

CREATE TABLE IF NOT EXISTS public.employee_shift_config (
    id BIGSERIAL PRIMARY KEY,
    year_month VARCHAR(7) NOT NULL,
    employee_id VARCHAR(64) NOT NULL,
    english_name VARCHAR(128) NOT NULL,
    shift_time_range VARCHAR(64) NOT NULL,
    shift_checkin_time TIME NOT NULL,
    shift_checkout_time TIME NOT NULL,
    monthly_rest_days VARCHAR(128) NOT NULL DEFAULT '',
    region_code VARCHAR(16) NOT NULL DEFAULT '',
    shift_timezone VARCHAR(64) NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (year_month, employee_id)
);

CREATE TABLE IF NOT EXISTS public.employee_shift_calendar (
    id BIGSERIAL PRIMARY KEY,
    year_month VARCHAR(7) NOT NULL,
    employee_id VARCHAR(64) NOT NULL,
    work_date DATE NOT NULL,
    cell_raw TEXT NOT NULL DEFAULT '',
    shift_code VARCHAR(16) NOT NULL DEFAULT '',
    cell_kind VARCHAR(16) NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (year_month, employee_id, work_date)
);

CREATE TABLE IF NOT EXISTS public.employee_shift_roster (
    year_month VARCHAR(7) NOT NULL,
    source VARCHAR(16) NOT NULL,
    employee_id VARCHAR(64) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (year_month, source, employee_id)
);

CREATE INDEX IF NOT EXISTS idx_employee_shift_roster_month_source
    ON public.employee_shift_roster (year_month, source);

CREATE TABLE IF NOT EXISTS public.clock_records (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    file_id TEXT NOT NULL,
    tg_id BIGINT NOT NULL,
    employee_id TEXT NOT NULL,
    shift_id BIGINT,
    clock_time TIMESTAMPTZ NOT NULL,
    clock_action VARCHAR(16),
    source_chat_id BIGINT,
    source_message_id BIGINT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_clock_records_telegram_source
    ON public.clock_records (source_chat_id, source_message_id)
    WHERE source_chat_id IS NOT NULL AND source_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.temporary_leave_records (
    id BIGSERIAL PRIMARY KEY,
    employee_id VARCHAR(64) NOT NULL,
    english_name VARCHAR(128) NOT NULL,
    tg_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    leave_at TIMESTAMPTZ NOT NULL,
    back_at TIMESTAMPTZ,
    duration_minutes INTEGER,
    reason TEXT,
    remark_required BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN' CHECK (
        status IN ('OPEN', 'CLOSED')
    )
);

CREATE INDEX IF NOT EXISTS idx_temporary_leave_records_open
    ON public.temporary_leave_records (employee_id, chat_id, leave_at DESC)
    WHERE status = 'OPEN';
