ALTER TABLE public.clock_records
    ADD COLUMN IF NOT EXISTS source_bot_owner TEXT,
    ADD COLUMN IF NOT EXISTS source_chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS source_message_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'clock_records_source_shape_check'
          AND conrelid = 'public.clock_records'::regclass
    ) THEN
        ALTER TABLE public.clock_records
            ADD CONSTRAINT clock_records_source_shape_check
            CHECK (
                (source_bot_owner IS NULL
                    AND source_chat_id IS NULL
                    AND source_message_id IS NULL)
                OR
                (source_bot_owner IN ('legacy_attendance', 'ux_assistant')
                    AND source_chat_id IS NOT NULL
                    AND source_message_id IS NOT NULL)
            ) NOT VALID;
        ALTER TABLE public.clock_records
            VALIDATE CONSTRAINT clock_records_source_shape_check;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_clock_records_telegram_source
    ON public.clock_records (
        source_chat_id,
        source_message_id
    )
    WHERE source_chat_id IS NOT NULL
      AND source_message_id IS NOT NULL;
