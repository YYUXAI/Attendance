from __future__ import annotations

from repositories.registrations_repo import RegistrationRow
from services import register_service


def test_confirm_register_rejects_unknown_employee_without_inserting(monkeypatch):
    preview = register_service.preview_register(tg_id=1001, text="GRANDFOR$74808")
    assert hasattr(preview, "token")
    calls = []

    monkeypatch.setattr(register_service.registrations_repo, "get_by_tg_id", lambda tg_id: None)
    monkeypatch.setattr(register_service.registrations_repo, "get_by_employee_id", lambda employee_id: None)
    monkeypatch.setattr(
        register_service.registrations_repo,
        "insert_registration",
        lambda **kwargs: calls.append(kwargs),
    )

    result = register_service.confirm_register(
        token=preview.token,
        tg_id=1001,
        registered_chat_id=1001,
        tg_username="owner",
    )

    assert not result.ok
    assert result.error_code == "EMPLOYEE_NOT_PRE_REGISTERED"
    assert calls == []


def test_confirm_register_binds_matching_pre_registered_employee(monkeypatch):
    preview = register_service.preview_register(tg_id=1002, text="grandfor$74808")
    assert hasattr(preview, "token")
    calls = []

    monkeypatch.setattr(register_service.registrations_repo, "get_by_tg_id", lambda tg_id: None)
    monkeypatch.setattr(
        register_service.registrations_repo,
        "get_by_employee_id",
        lambda employee_id: RegistrationRow(
            id=1,
            employee_id=str(employee_id),
            tg_id=None,
            english_name="GRANDFOR",
            tg_username=None,
            registered_chat_id=None,
            organization_id=None,
            shift_id=None,
        ),
    )
    monkeypatch.setattr(
        register_service.registrations_repo,
        "bind_tg_to_registration",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    result = register_service.confirm_register(
        token=preview.token,
        tg_id=1002,
        registered_chat_id=1002,
        tg_username="owner",
    )

    assert result.ok
    assert result.message == "您成功注册"
    assert calls[0]["employee_id"] == "74808"
    assert calls[0]["english_name"] == "GRANDFOR"


def test_confirm_register_rejects_employee_name_mismatch(monkeypatch):
    preview = register_service.preview_register(tg_id=1003, text="WRONG$74808")
    assert hasattr(preview, "token")
    calls = []

    monkeypatch.setattr(register_service.registrations_repo, "get_by_tg_id", lambda tg_id: None)
    monkeypatch.setattr(
        register_service.registrations_repo,
        "get_by_employee_id",
        lambda employee_id: RegistrationRow(
            id=1,
            employee_id=str(employee_id),
            tg_id=None,
            english_name="GRANDFOR",
            tg_username=None,
            registered_chat_id=None,
            organization_id=None,
            shift_id=None,
        ),
    )
    monkeypatch.setattr(
        register_service.registrations_repo,
        "bind_tg_to_registration",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    result = register_service.confirm_register(
        token=preview.token,
        tg_id=1003,
        registered_chat_id=1003,
        tg_username="owner",
    )

    assert not result.ok
    assert result.error_code == "EMPLOYEE_NAME_MISMATCH"
    assert calls == []
