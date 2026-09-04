CREATE TABLE IF NOT EXISTS public.attendance_operational_incident_acknowledgements (
  incident_kind TEXT NOT NULL CHECK (
    incident_kind IN ('delivery-receipt', 'worker-action', 'schedule-run')
  ),
  incident_id TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
  acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (incident_kind, incident_id)
);
