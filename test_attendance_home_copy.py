from contextlib import nullcontext
from types import SimpleNamespace

import gateway_provider.summary_module as summary_module
from repositories.registration_sessions_repo import ConfirmResult
from services import register_service


def _summary(monkeypatch, *, profile: object | None):
    monkeypatch.setattr(
        summary_module,
        "database_url_scope",
        lambda _database_url: nullcontext(),
    )
    monkeypatch.setattr(
        summary_module,
        "get_registration_profile_by_tg_id",
        lambda *, tg_id: profile,
    )
    return summary_module.read_attendance_summary(
        database_url="unused",
        telegram_user_id=81001,
    )


def test_unbound_home_summary_only_offers_attendance_binding(monkeypatch) -> None:
    summary = _summary(monkeypatch, profile=None)

    assert summary.registration.status == "UNBOUND"
    assert [line.order for line in summary.shellPresentation.lines] == [200]
    assert [line.text for line in summary.shellPresentation.lines] == [
        "考勤资料：未绑定"
    ]
    assert [
        button.text
        for row in summary.shellPresentation.actionRows
        for button in row.buttons
    ] == ["绑定考勤资料"]


def test_bound_home_summary_does_not_publish_internal_department(monkeypatch) -> None:
    summary = _summary(
        monkeypatch,
        profile=SimpleNamespace(department_name="CH"),
    )

    assert summary.registration.status == "BOUND"
    assert [line.text for line in summary.shellPresentation.lines] == [
        "考勤资料：已绑定"
    ]
    assert summary.shellPresentation.actionRows == []


def test_registration_success_says_attendance_is_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        register_service.registration_sessions_repo,
        "confirm_and_bind",
        lambda *_args, **_kwargs: ConfirmResult(code="ok"),
    )

    result = register_service.confirm_register(
        object(),
        token="test-token",
        tg_id=81001,
        registered_chat_id=81001,
        tg_username="test-user",
    )

    assert result.ok is True
    assert result.message == "考勤资料绑定成功，可以立即使用考勤。"
