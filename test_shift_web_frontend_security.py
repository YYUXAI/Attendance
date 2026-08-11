from __future__ import annotations

from pathlib import Path


def test_shift_frontend_does_not_read_credentials_from_url() -> None:
    html = (Path(__file__).parent / "web" / "shift_app" / "index.html").read_text(encoding="utf-8")

    assert "params.get('web_session')" not in html
    assert "params.get('api_token')" not in html
    assert "params.get('initData')" not in html
    assert "params.get('init_data')" not in html
    assert "tgWebAppData" not in html
    assert "'web_session=' + encodeURIComponent" not in html


def test_shift_frontend_exchanges_init_data_only_with_gateway() -> None:
    html = (Path(__file__).parent / "web" / "shift_app" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "/api/v1/webapp/session" in html
    assert "/api/v1/webapp/session/exchange" in html
    assert 'protocolVersion: \'1.0\'' in html
    assert "/api/v1/shift-config/exchange-session" not in html
    assert "X-Telegram-Init-Data" not in html
    assert "X-Web-Session" not in html
    assert "Authorization" in html
    assert "/api/v1/shift-config/send-template" not in html
    assert "/api/v1/shift-config/send-export" not in html


def test_shift_frontend_auth_retry_reuses_the_gateway_session_exchange() -> None:
    html = (Path(__file__).parent / "web" / "shift_app" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "async function exchangeGatewaySession()" in html
    assert "exchangeSessionFromInitData" not in html
