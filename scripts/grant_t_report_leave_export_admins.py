#!/usr/bin/env python3
"""Grant T-上班报备群 leave-export admins + bind known tg_id."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories import admin_list_repo, registrations_repo

EXPORT_CHAT_ID = -1002176838761
EXPORT_CHAT_TITLE = "T-上班报备群"
ADMINS = (
    ("2035", "Bert", "san_te01"),
    ("55648", "BALMLAW", "Y_YY_balmlaw"),
    ("42649", "Lawrencium", "y_yy_lawrencium1"),
    ("15416", "Reagen", "Y_YY_Reagen66"),
    ("59327", "ASSHTON", "Y_YY_ASSHTON"),
)


def _ensure_db_env() -> None:
    if os.getenv("DB_PASSWORD"):
        return
    pw_file = (os.getenv("ATTENDANCE_DATABASE_PASSWORD_FILE") or "").strip()
    if pw_file and Path(pw_file).is_file():
        os.environ["DB_PASSWORD"] = Path(pw_file).read_text(encoding="utf-8").strip()
    for src, dst in (
        ("ATTENDANCE_DATABASE_HOST", "DB_HOST"),
        ("ATTENDANCE_DATABASE_PORT", "DB_PORT"),
        ("ATTENDANCE_DATABASE_NAME", "DB_NAME"),
        ("ATTENDANCE_DATABASE_USER", "DB_USER"),
    ):
        val = (os.getenv(src) or os.getenv(dst) or "").strip()
        if val:
            os.environ[dst] = val


def _upsert_export_scope(*, employee_id: str) -> None:
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
            ("admin_export_chat_scope", employee_id, str(int(EXPORT_CHAT_ID))),
        )


def _bind_known_tg_ids() -> None:
    from infra.db import get_cursor

    with get_cursor() as cur:
        for employee_id, _name, username in ADMINS:
            cur.execute(
                """
                SELECT tg_id
                FROM public.temporary_leave_records
                WHERE employee_id = %s
                ORDER BY leave_at DESC
                LIMIT 1
                """,
                (employee_id,),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                continue
            registrations_repo.bind_tg_id_if_username_matches_cur(
                cur,
                tg_id=int(row[0]),
                tg_username=username,
            )


def main() -> None:
    _ensure_db_env()
    _bind_known_tg_ids()
    for employee_id, name, username in ADMINS:
        reg = registrations_repo.get_by_employee_id(employee_id)
        if reg is None:
            print(f"MISSING {employee_id} {name} @{username}")
            continue
        inserted = admin_list_repo.grant_admin_by_employee_id(employee_id=employee_id)
        _upsert_export_scope(employee_id=employee_id)
        print(
            "OK",
            f"employee_id={employee_id}",
            f"name={name}",
            f"username={username}",
            f"tg_id={reg.tg_id}",
            f"admin_new={inserted}",
            f"export_chat={EXPORT_CHAT_ID}",
            f"export_title={EXPORT_CHAT_TITLE}",
            "menu=export_only",
        )


if __name__ == "__main__":
    main()
