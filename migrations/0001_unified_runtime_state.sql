CREATE TABLE IF NOT EXISTS public.attendance_registration_sessions (
    bot_owner TEXT NOT NULL,
    tg_id BIGINT NOT NULL,
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
    PRIMARY KEY (bot_owner, tg_id),
    CONSTRAINT attendance_registration_sessions_owner_check
        CHECK (bot_owner IN ('legacy_attendance', 'ux_assistant')),
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
    ON public.attendance_registration_sessions (bot_owner, preview_token_hash)
    WHERE preview_token_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_attendance_registration_sessions_expiry
    ON public.attendance_registration_sessions (
        LEAST(inactivity_expires_at, absolute_expires_at)
    );

CREATE TABLE IF NOT EXISTS public.attendance_telegram_update_inbox (
    bot_owner TEXT NOT NULL,
    update_id BIGINT NOT NULL,
    status TEXT NOT NULL,
    claim_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    first_received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    last_error_code TEXT,
    PRIMARY KEY (bot_owner, update_id),
    CONSTRAINT attendance_telegram_update_inbox_owner_check
        CHECK (bot_owner IN ('legacy_attendance', 'ux_assistant')),
    CONSTRAINT attendance_telegram_update_inbox_status_check
        CHECK (status IN ('processing', 'completed', 'failed')),
    CONSTRAINT attendance_telegram_update_inbox_claim_shape_check
        CHECK (
            (status = 'processing' AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL)
            OR
            (status IN ('completed', 'failed') AND claim_token IS NULL AND lease_expires_at IS NULL)
        )
);

CREATE INDEX IF NOT EXISTS idx_attendance_telegram_update_inbox_retry
    ON public.attendance_telegram_update_inbox (status, lease_expires_at, updated_at);
