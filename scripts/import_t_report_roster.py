#!/usr/bin/env python3
"""仅 T-上班报备群：按 @用户名预登记花名册。"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories import registrations_repo

ROSTER_PATH = Path(__file__).with_name("t_report_roster.json")


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


def main() -> None:
    _ensure_db_env()
    rows = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    stats: Counter[str] = Counter()
    for row in rows:
        action = registrations_repo.upsert_preregistered_employee(
            employee_id=str(row["employee_id"]).strip(),
            english_name=str(row["english_name"]).strip(),
            tg_username=str(row["tg_username"]).strip(),
        )
        stats[action] += 1
        print(
            f"  [{action}] {row['employee_id']} {row['english_name']} @{row['tg_username']}"
        )
    print(
        "done",
        " ".join(f"{k}={v}" for k, v in sorted(stats.items())),
        f"total={len(rows)}",
    )


if __name__ == "__main__":
    main()
