#!/usr/bin/env python3
"""Grant Singjang UX admin + export scope + test-group shift view."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories import admin_list_repo, registrations_repo

EMPLOYEE_ID = "56773"
EXPORT_CHAT_ID = -1004347063533  # ux助手考勤测试群
EXPORT_CHAT_TITLE = "ux助手考勤测试群"


def _ensure_db_env() -> None:
    if os.getenv("DB_PASSWORD"):
        return
    pw_file = (os.getenv("ATTENDANCE_DATABASE_PASSWORD_FILE") or "").strip()
    if pw_file and Path(pw_file).is_file():
        os.environ["DB_PASSWORD"] = Path(pw_file).read_text(encoding="utf-8").strip()
    host = (os.getenv("ATTENDANCE_DATABASE_HOST") or os.getenv("DB_HOST") or "").strip()
    port = (os.getenv("ATTENDANCE_DATABASE_PORT") or os.getenv("DB_PORT") or "").strip()
    name = (os.getenv("ATTENDANCE_DATABASE_NAME") or os.getenv("DB_NAME") or "").strip()
    user = (os.getenv("ATTENDANCE_DATABASE_USER") or os.getenv("DB_USER") or "").strip()
    if host:
        os.environ["DB_HOST"] = host
    if port:
        os.environ["DB_PORT"] = port
    if name:
        os.environ["DB_NAME"] = name
    if user:
        os.environ["DB_USER"] = user


def _upsert_fact(*, fact_kind: str, subject_key: str, value_text: str) -> None:
    from infra.db import get_cursor

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.attendance_business_facts (
                fact_kind, subject_key, value_text, updated_at
            ) VALUES (%s, %s, %s, clock_timestamp())
            ON CONFLICT (fact_kind, subject_key) DO UPDATE
            SET value_text = EXCLUDED.value_text,
                updated_at = clock_timestamp()
            """,
            (fact_kind, subject_key, value_text),
        )


def main() -> None:
    _ensure_db_env()
    reg = registrations_repo.get_by_employee_id(EMPLOYEE_ID)
    if reg is None:
        raise SystemExit(f"registration not found for employee_id={EMPLOYEE_ID}")
    inserted = admin_list_repo.grant_admin_by_employee_id(employee_id=EMPLOYEE_ID)
    _upsert_fact(
        fact_kind="admin_export_chat_scope",
        subject_key=EMPLOYEE_ID,
        value_text=str(int(EXPORT_CHAT_ID)),
    )
    print(
        "OK",
        f"employee_id={EMPLOYEE_ID}",
        f"english_name={reg.english_name}",
        f"tg_id={reg.tg_id}",
        f"admin_new={inserted}",
        f"export_chat={EXPORT_CHAT_ID}",
        f"export_title={EXPORT_CHAT_TITLE}",
        "shift_view=test_group",
    )


if __name__ == "__main__":
    main()
