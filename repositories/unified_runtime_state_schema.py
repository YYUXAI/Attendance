from __future__ import annotations

from pathlib import Path

from infra.db import get_cursor


_MIGRATIONS_PATH = Path(__file__).resolve().parents[1] / "migrations"
_FUSION_MIGRATIONS = (
    "0001_unified_runtime_state.sql",
    "0002_telegram_checkin_source_idempotency.sql",
)


def ensure_tables() -> None:
    with get_cursor() as cur:
        for migration_name in _FUSION_MIGRATIONS:
            migration_path = _MIGRATIONS_PATH / migration_name
            cur.execute(migration_path.read_text(encoding="utf-8"))
