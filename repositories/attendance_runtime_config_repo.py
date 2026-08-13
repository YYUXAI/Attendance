from __future__ import annotations

import os
from collections.abc import Iterable

from psycopg2.extensions import cursor as Cursor

from infra.attendance_group_policy import AttendanceGroupPolicy, policy_for_title
from infra.db import get_cursor


def bind_observed_group_cur(
    cursor: Cursor,
    *,
    chat_id: int,
    route_ref: str,
    title: str | None,
    policies: Iterable[AttendanceGroupPolicy],
    config_fingerprint: str,
) -> None:
    policy = policy_for_title(policies, title)
    if policy is None:
        raise RuntimeError("Observed Attendance group is absent from active policy")
    cursor.execute(
        """
        INSERT INTO public.attendance_runtime_group_policies (
            chat_id, route_ref, title, roster_source, capabilities,
            config_fingerprint, observed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp())
        ON CONFLICT (chat_id) DO UPDATE
        SET route_ref = EXCLUDED.route_ref,
            title = EXCLUDED.title,
            roster_source = EXCLUDED.roster_source,
            capabilities = EXCLUDED.capabilities,
            config_fingerprint = EXCLUDED.config_fingerprint,
            observed_at = clock_timestamp()
        """,
        (
            int(chat_id),
            route_ref,
            policy.title,
            policy.roster,
            sorted(policy.capabilities),
            config_fingerprint,
        ),
    )


def active_chat_ids_for_roster(*, roster_source: str) -> tuple[int, ...]:
    fingerprint = _required_fingerprint()
    with get_cursor() as cursor:
        cursor.execute(
            """
            SELECT chat_id
            FROM public.attendance_runtime_group_policies
            WHERE config_fingerprint = %s AND roster_source = %s
            ORDER BY chat_id
            """,
            (fingerprint, roster_source),
        )
        return tuple(int(row[0]) for row in cursor.fetchall())


def active_chat_ids_with_capability(*, capability: str) -> tuple[int, ...]:
    fingerprint = _required_fingerprint()
    with get_cursor() as cursor:
        cursor.execute(
            """
            SELECT chat_id
            FROM public.attendance_runtime_group_policies
            WHERE config_fingerprint = %s AND %s = ANY(capabilities)
            ORDER BY chat_id
            """,
            (fingerprint, capability),
        )
        return tuple(int(row[0]) for row in cursor.fetchall())


def active_chat_ids() -> tuple[int, ...]:
    fingerprint = _required_fingerprint()
    with get_cursor() as cursor:
        cursor.execute(
            """
            SELECT chat_id
            FROM public.attendance_runtime_group_policies
            WHERE config_fingerprint = %s
            ORDER BY chat_id
            """,
            (fingerprint,),
        )
        return tuple(int(row[0]) for row in cursor.fetchall())


def active_chat_has_capability(*, chat_id: int, capability: str) -> bool:
    fingerprint = _required_fingerprint()
    with get_cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM public.attendance_runtime_group_policies
            WHERE config_fingerprint = %s
              AND chat_id = %s
              AND %s = ANY(capabilities)
            """,
            (fingerprint, int(chat_id), capability),
        )
        return cursor.fetchone() is not None


def business_fact_map(*, fact_kind: str) -> dict[str, str]:
    with get_cursor() as cursor:
        cursor.execute(
            """
            SELECT subject_key, value_text
            FROM public.attendance_business_facts
            WHERE fact_kind = %s
            ORDER BY subject_key
            """,
            (fact_kind,),
        )
        return {str(subject): str(value) for subject, value in cursor.fetchall()}


def business_fact_set(*, fact_kind: str) -> frozenset[str]:
    return frozenset(business_fact_map(fact_kind=fact_kind))


def _required_fingerprint() -> str:
    value = (os.environ.get("ATTENDANCE_GROUPS_FINGERPRINT") or "").strip()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("ATTENDANCE_GROUPS_FINGERPRINT is required")
    return value
