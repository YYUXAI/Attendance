from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from repositories import registration_sessions_repo
from repositories.registrations_repo import RegistrationRow


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executions = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def _context(cursor):
    @contextmanager
    def manager():
        yield cursor

    return manager


def test_save_preview_hashes_token_before_storage(monkeypatch):
    now = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(minutes=15)
    cursor = FakeCursor(rows=[(expires_at,)])
    monkeypatch.setattr(registration_sessions_repo, "get_cursor", _context(cursor))

    result = registration_sessions_repo.save_preview(
        bot_owner="ux_assistant",
        tg_id=1,
        private_chat_id=1,
        english_name="NAME",
        employee_id="EMPLOYEE",
        token="raw-secret-token",
        now=now,
        inactivity_ttl=timedelta(minutes=15),
    )

    assert result == expires_at
    params = cursor.executions[0][1]
    assert "raw-secret-token" not in params
    assert len(params[2]) == 64


def test_confirm_and_bind_locks_session_and_commits_binding_and_consumption_together(
    monkeypatch,
):
    now = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
    cursor = FakeCursor(
        rows=[
            (
                2,
                2,
                "NAME",
                "EMPLOYEE",
                now + timedelta(minutes=15),
                now + timedelta(minutes=15),
                now + timedelta(minutes=15),
            )
        ]
    )
    monkeypatch.setattr(registration_sessions_repo, "transaction", _context(cursor))
    monkeypatch.setattr(
        registration_sessions_repo.registrations_repo,
        "get_by_tg_id_cur",
        lambda cur, *, tg_id: None,
    )
    monkeypatch.setattr(
        registration_sessions_repo.registrations_repo,
        "get_by_employee_id_cur",
        lambda cur, *, employee_id: RegistrationRow(
            id=1,
            employee_id=employee_id,
            tg_id=None,
            english_name="NAME",
            tg_username=None,
            registered_chat_id=None,
            organization_id=None,
            shift_id=None,
        ),
    )
    bind_calls = []
    monkeypatch.setattr(
        registration_sessions_repo.registrations_repo,
        "bind_tg_to_registration_cur",
        lambda cur, **kwargs: bind_calls.append((cur, kwargs)) or True,
    )

    result = registration_sessions_repo.confirm_and_bind(
        bot_owner="ux_assistant",
        token="opaque",
        tg_id=2,
        private_chat_id=2,
        tg_username=None,
        now=now,
    )

    assert result.code == "ok"
    assert "FOR UPDATE" in cursor.executions[0][0]
    assert bind_calls[0][0] is cursor
    assert cursor.executions[-1][0].lstrip().startswith("DELETE")


def test_cross_actor_confirm_does_not_consume_owner_session(monkeypatch):
    now = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
    cursor = FakeCursor(
        rows=[
            (
                3,
                3,
                "NAME",
                "EMPLOYEE",
                now + timedelta(minutes=15),
                now + timedelta(minutes=15),
                now + timedelta(minutes=15),
            )
        ]
    )
    monkeypatch.setattr(registration_sessions_repo, "transaction", _context(cursor))

    result = registration_sessions_repo.confirm_and_bind(
        bot_owner="ux_assistant",
        token="opaque",
        tg_id=999,
        private_chat_id=999,
        tg_username=None,
        now=now,
    )

    assert result.code == "owner_mismatch"
    assert len(cursor.executions) == 1


def test_attendance_admin_binding_uses_the_same_existing_registration_contract(monkeypatch):
    now = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
    cursor = FakeCursor(rows=[(
        4,
        4,
        "ADMIN",
        "ADMIN-EMPLOYEE",
        now + timedelta(minutes=15),
        now + timedelta(minutes=15),
        now + timedelta(minutes=15),
    )])
    monkeypatch.setattr(registration_sessions_repo, "transaction", _context(cursor))
    monkeypatch.setattr(
        registration_sessions_repo.registrations_repo,
        "get_by_tg_id_cur",
        lambda cur, *, tg_id: None,
    )
    monkeypatch.setattr(
        registration_sessions_repo.registrations_repo,
        "get_by_employee_id_cur",
        lambda cur, *, employee_id: RegistrationRow(
            id=1,
            employee_id=employee_id,
            tg_id=None,
            english_name="ADMIN",
            tg_username=None,
            registered_chat_id=None,
            organization_id=None,
            shift_id=None,
        ),
    )
    monkeypatch.setattr(
        registration_sessions_repo.registrations_repo,
        "bind_tg_to_registration_cur",
        lambda *args, **kwargs: True,
    )

    result = registration_sessions_repo.confirm_and_bind(
        bot_owner="ux_assistant",
        token="opaque",
        tg_id=4,
        private_chat_id=4,
        tg_username=None,
        now=now,
    )

    assert result.code == "ok"
    sql = "\n".join(statement for statement, _params in cursor.executions)
    assert "FROM public.admin_list" not in sql
    assert cursor.executions[-1][0].lstrip().startswith("DELETE")


def test_migration_defines_owner_namespaced_persistent_state():
    migration = (
        registration_sessions_repo.__file__
        and registration_sessions_repo.__file__
    )
    assert migration
    from pathlib import Path

    sql = (
        Path(registration_sessions_repo.__file__).resolve().parents[1]
        / "migrations"
        / "0001_unified_runtime_state.sql"
    ).read_text(encoding="utf-8")
    assert "PRIMARY KEY (bot_owner, tg_id)" in sql
    assert "PRIMARY KEY (bot_owner, update_id)" in sql
    assert "preview_token_hash" in sql
    assert "absolute_expires_at" in sql
