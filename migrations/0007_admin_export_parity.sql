CREATE TABLE IF NOT EXISTS public.attendance_admin_export_sessions (
    tg_id BIGINT PRIMARY KEY,
    private_chat_id BIGINT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN (
        'waiting_shift_id',
        'waiting_start_date',
        'waiting_end_date',
        'waiting_confirm'
    )),
    shift_id BIGINT,
    start_date DATE,
    end_date DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '15 minutes')
);
