from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.run_provider_migrations import (
    MigrationChecksumMismatch,
    apply_provider_migrations,
    read_provider_migrations,
)


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.row: tuple[str] | None = None

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> None:
        normalized = " ".join(statement.split())
        if normalized.startswith("SELECT checksum FROM attendance_provider_migrations"):
            checksum = self.connection.applied.get(str(parameters[0]))
            self.row = (checksum,) if checksum else None
        elif normalized.startswith("INSERT INTO attendance_provider_migrations"):
            self.connection.applied[str(parameters[0])] = str(parameters[1])
        elif normalized.startswith(("SELECT pg_advisory", "CREATE TABLE")):
            self.row = None
        else:
            self.connection.executed_migrations.append(statement)

    def fetchone(self) -> tuple[str] | None:
        return self.row


class _Connection:
    def __init__(self, applied: dict[str, str] | None = None) -> None:
        self.applied = dict(applied or {})
        self.executed_migrations: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_provider_migrations_are_ordered_and_idempotent(tmp_path: Path) -> None:
    (tmp_path / "0005_last.sql").write_text("SELECT 'last';\n", encoding="utf-8")
    (tmp_path / "0003_first.sql").write_text("SELECT 'first';\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignored", encoding="utf-8")
    migrations = read_provider_migrations(tmp_path)
    connection = _Connection()

    apply_provider_migrations(connection, migrations)
    apply_provider_migrations(connection, migrations)

    assert [migration.name for migration in migrations] == [
        "0003_first.sql",
        "0005_last.sql",
    ]
    assert connection.executed_migrations == ["SELECT 'first';\n", "SELECT 'last';\n"]
    assert connection.applied == {
        migration.name: hashlib.sha256(migration.sql.encode("utf-8")).hexdigest()
        for migration in migrations
    }


def test_provider_migration_rejects_changed_applied_sql(tmp_path: Path) -> None:
    migration_path = tmp_path / "0003_gateway_provider.sql"
    migration_path.write_text("SELECT 1;\n", encoding="utf-8")
    migration = read_provider_migrations(tmp_path)[0]
    connection = _Connection({migration.name: "0" * 64})

    with pytest.raises(MigrationChecksumMismatch, match=migration.name):
        apply_provider_migrations(connection, [migration])

    assert connection.executed_migrations == []
    assert connection.rollbacks == 1
