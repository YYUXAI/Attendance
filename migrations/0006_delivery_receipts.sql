CREATE TABLE IF NOT EXISTS public.attendance_gateway_delivery_receipts (
    receipt_id VARCHAR(128) PRIMARY KEY,
    action_id VARCHAR(128) NOT NULL UNIQUE,
    related_event_id VARCHAR(128),
    correlation_id VARCHAR(256),
    request_hash CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    receipt_payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT attendance_gateway_delivery_receipts_identity_format CHECK (
        receipt_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
        AND action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
        AND (
            related_event_id IS NULL
            OR related_event_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
        )
    ),
    CONSTRAINT attendance_gateway_delivery_receipts_correlation CHECK (
        (related_event_id IS NOT NULL AND correlation_id IS NULL)
        OR (related_event_id IS NULL AND correlation_id IS NOT NULL)
    ),
    CONSTRAINT attendance_gateway_delivery_receipts_request_hash CHECK (
        request_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT attendance_gateway_delivery_receipts_status CHECK (
        status IN (
            'DELIVERED',
            'PERMANENTLY_FAILED',
            'UNCERTAIN',
            'SUPERSEDED'
        )
    ),
    CONSTRAINT attendance_gateway_delivery_receipts_payload CHECK (
        jsonb_typeof(receipt_payload) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS idx_attendance_gateway_delivery_receipts_event
    ON public.attendance_gateway_delivery_receipts (related_event_id)
    WHERE related_event_id IS NOT NULL;
