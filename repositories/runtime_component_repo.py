from __future__ import annotations

from datetime import datetime, timezone

import psycopg2


COMPONENTS = ("provider", "webapp", "scheduler", "worker")


def record_runtime_component(
    *, database_url: str, component: str, public_config_fingerprint: str
) -> None:
    if component not in COMPONENTS:
        raise ValueError("runtime component is invalid")
    if len(public_config_fingerprint) != 64:
        raise ValueError("public config fingerprint is invalid")
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.attendance_runtime_components (
                    component, public_config_fingerprint, heartbeat_at
                )
                VALUES (%s, %s, clock_timestamp())
                ON CONFLICT (component) DO UPDATE
                SET public_config_fingerprint = EXCLUDED.public_config_fingerprint,
                    heartbeat_at = clock_timestamp()
                """,
                (component, public_config_fingerprint),
            )


def read_runtime_component_state(
    *, database_url: str, expected_fingerprint: str
) -> dict[str, object]:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT component, public_config_fingerprint, heartbeat_at
                FROM public.attendance_runtime_components
                ORDER BY component
                """
            )
            rows = cursor.fetchall()
    observed = {
        str(component): {
            "fingerprint": str(fingerprint),
            "match": str(fingerprint) == expected_fingerprint,
            "heartbeatAt": heartbeat.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if isinstance(heartbeat, datetime)
            else None,
        }
        for component, fingerprint, heartbeat in rows
    }
    return {
        "expectedFingerprint": expected_fingerprint,
        "components": {
            component: observed.get(component, {"fingerprint": None, "match": False, "heartbeatAt": None})
            for component in COMPONENTS
        },
        "match": all(
            component in observed and bool(observed[component]["match"])
            for component in COMPONENTS
        ),
    }
