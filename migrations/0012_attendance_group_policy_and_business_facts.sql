CREATE TABLE IF NOT EXISTS public.attendance_runtime_group_policies (
    chat_id BIGINT PRIMARY KEY,
    route_ref VARCHAR(192) NOT NULL UNIQUE,
    title VARCHAR(128) NOT NULL,
    roster_source VARCHAR(16) NOT NULL,
    capabilities TEXT[] NOT NULL,
    config_fingerprint CHAR(64) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT attendance_runtime_group_policy_roster
        CHECK (roster_source IN ('main', 'alt')),
    CONSTRAINT attendance_runtime_group_policy_fingerprint
        CHECK (config_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_attendance_runtime_group_policy_active
    ON public.attendance_runtime_group_policies (config_fingerprint, roster_source);

CREATE TABLE IF NOT EXISTS public.attendance_runtime_components (
    component VARCHAR(16) PRIMARY KEY,
    public_config_fingerprint CHAR(64) NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT attendance_runtime_component_name
        CHECK (component IN ('provider', 'webapp', 'scheduler', 'worker')),
    CONSTRAINT attendance_runtime_component_fingerprint
        CHECK (public_config_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS public.attendance_business_facts (
    fact_kind VARCHAR(64) NOT NULL,
    subject_key VARCHAR(128) NOT NULL,
    value_text TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (fact_kind, subject_key),
    CONSTRAINT attendance_business_fact_kind
        CHECK (fact_kind ~ '^[a-z][a-z0-9_]{2,63}$'),
    CONSTRAINT attendance_business_fact_subject_nonempty
        CHECK (length(btrim(subject_key)) > 0)
);
