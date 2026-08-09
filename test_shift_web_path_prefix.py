from pathlib import Path


def test_shift_web_provider_calls_follow_the_page_path_prefix() -> None:
    html = Path("web/shift_app/index.html").read_text(encoding="utf-8")

    assert "const providerBasePath" in html
    assert "return providerBasePath + path" in html
    assert "fetch(apiUrl('/api/v1/webapp/session/exchange')" in html
