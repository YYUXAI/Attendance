from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from repositories import attendance_runtime_config_repo, runtime_component_repo


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []
        self.executions: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, parameters: tuple[object, ...] | None = None) -> None:
        self.executions.append((statement, parameters))

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self._cursor


def test_runtime_component_state_requires_all_four_matching_fingerprints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "a" * 64
    rows = [
        ("provider", expected, datetime(2026, 8, 13, tzinfo=timezone.utc)),
        ("webapp", expected, datetime(2026, 8, 13, tzinfo=timezone.utc)),
        ("scheduler", "b" * 64, datetime(2026, 8, 13, tzinfo=timezone.utc)),
    ]
    cursor = _Cursor(rows)
    monkeypatch.setattr(
        runtime_component_repo.psycopg2,
        "connect",
        lambda _database_url: _Connection(cursor),
    )

    state = runtime_component_repo.read_runtime_component_state(
        database_url="postgresql://unit.invalid/attendance",
        expected_fingerprint=expected,
    )

    assert state["match"] is False
    assert state["components"]["provider"]["match"] is True
    assert state["components"]["scheduler"]["match"] is False
    assert state["components"]["worker"] == {
        "fingerprint": None,
        "match": False,
        "heartbeatAt": None,
    }


def test_group_registry_filters_every_read_by_active_config_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = "c" * 64
    monkeypatch.setenv("ATTENDANCE_GROUPS_FINGERPRINT", fingerprint)
    cursor = _Cursor([(-10001,), (-10002,)])

    @contextmanager
    def fake_cursor():
        yield cursor

    monkeypatch.setattr(attendance_runtime_config_repo, "get_cursor", fake_cursor)

    assert attendance_runtime_config_repo.active_chat_ids_with_capability(
        capability="export-scope"
    ) == (-10001, -10002)
    statement, parameters = cursor.executions[-1]
    assert "config_fingerprint = %s" in statement
    assert parameters == (fingerprint, "export-scope")


def test_group_registry_rejects_missing_active_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ATTENDANCE_GROUPS_FINGERPRINT", raising=False)
    with pytest.raises(RuntimeError, match="ATTENDANCE_GROUPS_FINGERPRINT is required"):
        attendance_runtime_config_repo.active_chat_ids()
