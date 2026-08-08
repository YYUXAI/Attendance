CREATE TABLE IF NOT EXISTS gateway_processed_events (
    event_id VARCHAR(128) PRIMARY KEY,
    request_hash CHAR(64) NOT NULL,
    response_json JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT gateway_processed_events_event_id_format CHECK (
        event_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
    ),
    CONSTRAINT gateway_processed_events_request_hash_format CHECK (
        request_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT gateway_processed_events_response_object CHECK (
        jsonb_typeof(response_json) = 'object'
    )
);
