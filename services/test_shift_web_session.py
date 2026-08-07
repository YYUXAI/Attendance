from __future__ import annotations

from services import shift_web_session


def test_shift_web_session_has_short_absolute_ttl(monkeypatch) -> None:
    now = [1_800_000_000.0]
    shift_web_session._sessions.clear()
    monkeypatch.setenv("SHIFT_WEB_SESSION_TTL_SECONDS", "300")
    monkeypatch.setattr(shift_web_session.time, "time", lambda: now[0])

    token = shift_web_session.create_session(tg_id=42)
    now[0] += 299
    assert shift_web_session.verify_session(token) == 42
    now[0] += 2
    assert shift_web_session.verify_session(token) is None
