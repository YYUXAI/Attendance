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
