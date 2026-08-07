from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(
    PROJECT_ROOT / ".env",
    override=True,
    encoding="utf-8",
)

from infra.db import get_cursor
from repositories import unified_runtime_state_schema


EXPECTED_TABLES = (
    "attendance_registration_sessions",
    "attendance_telegram_update_inbox",
)


def _table_status() -> dict[str, bool]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name IN %s
            """,
            (EXPECTED_TABLES,),
        )
        existing = {str(row[0]) for row in (cur.fetchall() or [])}
    return {name: name in existing for name in EXPECTED_TABLES}


def _checkin_source_status() -> tuple[int, bool]:
    expected_columns = {
        "source_bot_owner",
        "source_chat_id",
        "source_message_id",
    }
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'clock_records'
              AND column_name IN %s
            """,
            (tuple(sorted(expected_columns)),),
        )
        columns = {str(row[0]) for row in (cur.fetchall() or [])}
        cur.execute(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'clock_records'
              AND indexname = 'uq_clock_records_telegram_source'
            """
        )
        unique_index = cur.fetchone() is not None
    return len(columns), unique_index


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply additive UX助手 Attendance runtime-state migration."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-additive", action="store_true")
    args = parser.parse_args()

    before = _table_status()
    columns_before, index_before = _checkin_source_status()
    if args.apply:
        if not args.confirm_additive:
            raise SystemExit("--apply requires --confirm-additive")
        unified_runtime_state_schema.ensure_tables()
    after = _table_status()
    columns_after, index_after = _checkin_source_status()
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "expected_tables": len(EXPECTED_TABLES),
                "present_before": sum(before.values()),
                "present_after": sum(after.values()),
                "checkin_source_columns_before": columns_before,
                "checkin_source_columns_after": columns_after,
                "checkin_source_index_before": index_before,
                "checkin_source_index_after": index_after,
                "ready": (
                    all(after.values())
                    and columns_after == 3
                    and index_after
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
