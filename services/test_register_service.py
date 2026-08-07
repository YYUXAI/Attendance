from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repositories.registration_sessions_repo import (
    ConfirmResult,
    RegistrationSessionRow,
)
from services import register_service


BOT_OWNER = "ux_assistant"


def _patch_preview_storage(monkeypatch, *, expires_at: datetime):
    calls = []

    def save_preview(**kwargs):
        calls.append(kwargs)
        return expires_at

    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "save_preview",
        save_preview,
    )
    return calls


def test_preview_register_persists_owner_user_chat_and_ttl(monkeypatch):
    now = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(minutes=15)
    calls = _patch_preview_storage(monkeypatch, expires_at=expires_at)

    preview = register_service.preview_register(
        bot_owner=BOT_OWNER,
        tg_id=1001,
        private_chat_id=1001,
        text="GRANDFOR$74808",
        now=now,
    )

    assert hasattr(preview, "token")
    assert preview.expires_at == expires_at
    assert calls[0]["bot_owner"] == BOT_OWNER
    assert calls[0]["tg_id"] == 1001
    assert calls[0]["private_chat_id"] == 1001
    assert calls[0]["inactivity_ttl"] == timedelta(minutes=15)


def test_preview_invalid_input_touches_persistent_session(monkeypatch):
    calls = []
    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "touch_invalid_input",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    result = register_service.preview_register(
        bot_owner=BOT_OWNER,
        tg_id=1002,
        private_chat_id=1002,
        text="invalid",
    )

    assert not result.ok
    assert result.error_code == "INVALID_FORMAT"
    assert calls[0]["bot_owner"] == BOT_OWNER


def test_preview_rejects_when_persistent_session_expired(monkeypatch):
    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "save_preview",
        lambda **kwargs: None,
    )

    result = register_service.preview_register(
        bot_owner=BOT_OWNER,
        tg_id=1003,
        private_chat_id=1003,
        text="GRANDFOR$74808",
    )

    assert not result.ok
    assert result.error_code == "SESSION_EXPIRED"


def test_begin_session_has_fifteen_minute_sliding_inactivity_expiry(monkeypatch):
    now = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
    calls = []
    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "begin_session",
        lambda **kwargs: calls.append(kwargs),
    )

    register_service.mark_waiting_register_input(
        bot_owner=BOT_OWNER,
        tg_id=2001,
        private_chat_id=2001,
        now=now,
    )

    assert calls[0]["inactivity_ttl"] == timedelta(minutes=15)
    assert "absolute_ttl" not in calls[0]


def test_confirm_register_maps_atomic_repository_success(monkeypatch):
    calls = []
    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "confirm_and_bind",
        lambda **kwargs: calls.append(kwargs) or ConfirmResult(code="ok"),
    )

    result = register_service.confirm_register(
        bot_owner=BOT_OWNER,
        token="opaque-token",
        tg_id=2002,
        registered_chat_id=2002,
        tg_username="display-only",
    )

    assert result.ok
    assert result.message == "您成功注册"
    assert calls[0]["bot_owner"] == BOT_OWNER
    assert calls[0]["private_chat_id"] == 2002


def test_confirm_register_rejects_cross_actor_token(monkeypatch):
    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "confirm_and_bind",
        lambda **kwargs: ConfirmResult(code="owner_mismatch"),
    )

    result = register_service.confirm_register(
        bot_owner=BOT_OWNER,
        token="opaque-token",
        tg_id=2999,
        registered_chat_id=2999,
        tg_username=None,
    )

    assert not result.ok
    assert result.error_code == "TOKEN_OWNER_MISMATCH"


def test_confirm_register_maps_business_failures(monkeypatch):
    expected = {
        "expired": "EXPIRED",
        "tg_already_bound": "TG_ALREADY_BOUND",
        "employee_not_pre_registered": "EMPLOYEE_NOT_PRE_REGISTERED",
        "employee_already_bound": "EMPLOYEE_ALREADY_BOUND",
        "employee_name_mismatch": "EMPLOYEE_NAME_MISMATCH",
    }
    for repository_code, service_code in expected.items():
        monkeypatch.setattr(
            register_service.registration_sessions_repo,
            "confirm_and_bind",
            lambda **kwargs: ConfirmResult(code=repository_code),
        )
        result = register_service.confirm_register(
            bot_owner=BOT_OWNER,
            token="opaque-token",
            tg_id=3001,
            registered_chat_id=3001,
            tg_username=None,
        )
        assert not result.ok
        assert result.error_code == service_code


def test_get_preview_reads_persistent_row(monkeypatch):
    now = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(minutes=15)
    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "get_preview",
        lambda **kwargs: RegistrationSessionRow(
            bot_owner=BOT_OWNER,
            tg_id=4001,
            private_chat_id=4001,
            stage="awaiting_confirmation",
            english_name="GRANDFOR",
            employee_id="74808",
            created_at=now,
            last_activity_at=now,
            inactivity_expires_at=expires_at,
            absolute_expires_at=expires_at,
            preview_expires_at=expires_at,
        ),
    )

    preview = register_service.get_preview(
        bot_owner=BOT_OWNER,
        token="opaque-token",
        tg_id=4001,
        private_chat_id=4001,
        now=now,
    )

    assert preview is not None
    assert preview.employee_id == "74808"
    assert preview.expires_at == expires_at


def test_english_name_matches_is_case_insensitive_but_exact():
    assert register_service.english_name_matches("GRANDFOR", "grandfor")
    assert not register_service.english_name_matches("GRANDFOR", "GRAND FOR")
