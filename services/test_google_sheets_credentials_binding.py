from __future__ import annotations

from unittest.mock import Mock

import pytest

from services import google_sheets_client


def test_google_client_consumes_in_memory_root_binding_not_a_checkout_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = Mock()
    monkeypatch.setattr(
        google_sheets_client.service_account.Credentials,
        "from_service_account_info",
        Mock(return_value=credentials),
    )
    monkeypatch.setattr(google_sheets_client, "build", Mock(return_value="service"))

    result = google_sheets_client._build_service(
        credentials_json='{"type":"service_account","project_id":"fixture"}'
    )

    assert result == "service"
    google_sheets_client.service_account.Credentials.from_service_account_info.assert_called_once()


def test_google_client_rejects_a_path_or_malformed_binding() -> None:
    with pytest.raises(RuntimeError, match="binding is invalid"):
        google_sheets_client._build_service(credentials_json="secrets/google.json")
