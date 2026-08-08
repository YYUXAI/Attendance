from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg2


_MIGRATION_FILE = re.compile(r"^\d+.*\.sql$")
_LOCK_NAME = "attendance_provider_migrations_v1"


class MigrationChecksumMismatch(RuntimeError):
    """An applied migration no longer matches its immutable source."""


@dataclass(frozen=True)
class ProviderMigration:
    name: str
    sql: str
    checksum: str


class _Cursor(Protocol):
    def __enter__(self) -> "_Cursor": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> None: ...

    def fetchone(self) -> tuple[str] | None: ...


class DatabaseConnection(Protocol):
    def cursor(self) -> _Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def read_provider_migrations(directory: Path) -> list[ProviderMigration]:
    migrations = []
    for path in sorted(
        (candidate for candidate in directory.iterdir() if candidate.is_file()),
        key=lambda candidate: candidate.name,
    ):
        if not _MIGRATION_FILE.fullmatch(path.name):
            continue
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            ProviderMigration(
                name=path.name,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    if not migrations:
        raise RuntimeError("No Attendance Provider migrations found")
    return migrations


def apply_provider_migrations(
    connection: DatabaseConnection,
    migrations: list[ProviderMigration],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(hashtext(%s))", (_LOCK_NAME,))
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance_provider_migrations (
                name TEXT PRIMARY KEY,
                checksum CHAR(64) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
                CONSTRAINT attendance_provider_migrations_checksum_format
                    CHECK (checksum ~ '^[0-9a-f]{64}$')
            )
            """
        )
        connection.commit()
        try:
            for migration in migrations:
                cursor.execute(
                    "SELECT checksum FROM attendance_provider_migrations WHERE name = %s",
                    (migration.name,),
                )
                applied = cursor.fetchone()
                if applied is not None:
                    if applied[0] != migration.checksum:
                        connection.rollback()
                        raise MigrationChecksumMismatch(
                            f"Applied Attendance migration checksum changed: {migration.name}"
                        )
                    connection.commit()
                    continue
                try:
                    cursor.execute(migration.sql)
                    cursor.execute(
                        """
                        INSERT INTO attendance_provider_migrations (name, checksum)
                        VALUES (%s, %s)
                        """,
                        (migration.name, migration.checksum),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        finally:
            cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_LOCK_NAME,))
            connection.commit()


def main() -> None:
    database_url = (os.environ.get("ATTENDANCE_DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("ATTENDANCE_DATABASE_URL is required")
    migrations = read_provider_migrations(
        Path(__file__).resolve().parents[1] / "migrations"
    )
    with psycopg2.connect(database_url, connect_timeout=5) as connection:
        apply_provider_migrations(connection, migrations)
    print(f"Applied {len(migrations)} Attendance Provider migrations")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Attendance Provider migration failed: {type(error).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
