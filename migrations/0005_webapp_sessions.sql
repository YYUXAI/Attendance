CREATE TABLE IF NOT EXISTS public.attendance_webapp_sessions (
    session_token_hash CHAR(64) PRIMARY KEY,
    gateway_session_id VARCHAR(128) NOT NULL UNIQUE,
    telegram_user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT attendance_webapp_session_token_hash_format CHECK (
        session_token_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT attendance_webapp_gateway_session_id_format CHECK (
        gateway_session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
    ),
    CONSTRAINT attendance_webapp_telegram_user_id_positive CHECK (
        telegram_user_id > 0
    ),
    CONSTRAINT attendance_webapp_session_expiry_order CHECK (
        expires_at > created_at
    )
);

CREATE INDEX IF NOT EXISTS idx_attendance_webapp_sessions_expiry
    ON public.attendance_webapp_sessions (expires_at);
