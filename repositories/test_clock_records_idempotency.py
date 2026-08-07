from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from repositories import clock_records_repo


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchone(self):
        return self.row


def _context(cursor):
    @contextmanager
    def manager():
        yield cursor

    return manager


def test_telegram_clock_insert_uses_atomic_source_conflict(monkeypatch):
    cursor = FakeCursor((1,))
    monkeypatch.setattr(clock_records_repo, "ensure_clock_action_column", lambda: None)
    monkeypatch.setattr(clock_records_repo, "get_cursor", _context(cursor))

    inserted = clock_records_repo.insert_telegram_clock_record(
        bot_owner="ux_assistant",
        source_chat_id=-1,
        source_message_id=10,
        file_id="file",
        tg_id=1,
        employee_id="employee",
        shift_id=None,
        clock_time_utc=datetime.now(timezone.utc),
        clock_action="签到",
    )

    assert inserted is True
    sql = cursor.executions[0][0]
    assert "ON CONFLICT" in sql
    assert "source_chat_id, source_message_id" in sql
    conflict_clause = sql.split("ON CONFLICT", 1)[1]
    assert "source_bot_owner" not in conflict_clause
    assert "DO NOTHING" in sql


def test_telegram_clock_precheck_is_cross_bot(monkeypatch):
    cursor = FakeCursor((1,))
    monkeypatch.setattr(clock_records_repo, "get_cursor", _context(cursor))

    assert clock_records_repo.has_telegram_source(
        bot_owner="ux_assistant",
        source_chat_id=-1,
        source_message_id=10,
    ) is True
    sql, params = cursor.executions[0]
    assert "source_bot_owner" not in sql
    assert params == (-1, 10)


def test_telegram_clock_replay_reports_not_inserted(monkeypatch):
    cursor = FakeCursor(None)
    monkeypatch.setattr(clock_records_repo, "ensure_clock_action_column", lambda: None)
    monkeypatch.setattr(clock_records_repo, "get_cursor", _context(cursor))

    inserted = clock_records_repo.insert_telegram_clock_record(
        bot_owner="ux_assistant",
        source_chat_id=-1,
        source_message_id=10,
        file_id="file",
        tg_id=1,
        employee_id="employee",
        shift_id=None,
        clock_time_utc=datetime.now(timezone.utc),
        clock_action="签到",
    )

    assert inserted is False
