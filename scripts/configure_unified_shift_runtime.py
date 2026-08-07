from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--omniai-root", default="/home/shawn/OmniAI2")
    parser.add_argument("--attendance-env", default=str(Path(__file__).resolve().parents[1] / ".env"))
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _unified_runtime_values(omniai_root: Path) -> tuple[str, str]:
    merged: dict[str, str | None] = {}
    for name in (".env", ".env.real"):
        path = omniai_root / name
        if path.is_file():
            merged.update(dotenv_values(path))
    raw = str(merged.get("UNIFIED_BOT_WEBAPP_BASE_URL") or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("unified_webapp_https_origin_missing")
    bot_token = str(merged.get("UNIFIED_BOT_TOKEN") or "").strip()
    if not bot_token:
        raise RuntimeError("unified_bot_token_missing")
    return f"{parsed.scheme}://{parsed.netloc}", bot_token


def _write(path: Path, values: dict[str, str]) -> None:
    original = path.read_text(encoding="utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=".env.shift-", dir=path.parent, text=True)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(original, encoding="utf-8")
        os.chmod(temp, 0o600)
        for key, value in values.items():
            set_key(str(temp), key, value, quote_mode="always")
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()


def main() -> int:
    args = _args()
    origin, bot_token = _unified_runtime_values(Path(args.omniai_root).resolve())
    attendance_env = Path(args.attendance_env).resolve()
    values = {
        "SHIFT_WEB_ENABLED": "true",
        "SHIFT_WEB_APP_PUBLIC_URL": origin,
        "SHIFT_WEB_HOST": "127.0.0.1",
        "SHIFT_WEB_PORT": "18084",
        "SHIFT_WEB_BROWSER_DEV": "false",
        "SHIFT_WEB_INIT_DATA_MAX_AGE_SECONDS": "300",
        "SHIFT_WEB_SESSION_TTL_SECONDS": "900",
        "SHIFT_WEB_TELEGRAM_BOT_TOKEN": bot_token,
    }
    current = dotenv_values(attendance_env)
    changed_keys = sum(1 for key, value in values.items() if str(current.get(key) or "") != value)
    if args.apply:
        _write(attendance_env, values)
    print(
        {
            "mode": "apply" if args.apply else "dry-run",
            "https_origin_configured": True,
            "keys_checked": len(values),
            "keys_different": changed_keys,
            "keys_changed": changed_keys if args.apply else 0,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
