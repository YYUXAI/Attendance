"""本仓库 Bot Token 仅来自 bot_gateway/.env（与服务器部署配置分离）。"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 历史线上 Bot ID；本地仓库不得使用其 Token
_FORBIDDEN_BOT_IDS = frozenset({8435627895})

_WORKSPACE = Path(__file__).resolve().parents[2]
_GATEWAY_ENV = _WORKSPACE / "bot_gateway" / ".env"
_ATTENDANCE_ENV = Path(__file__).resolve().parents[1] / ".env"


def bootstrap_bot_token_env() -> int:
    if not _GATEWAY_ENV.is_file():
        raise RuntimeError(
            "缺少 bot_gateway/.env。请执行: cp bot_gateway/.env.example bot_gateway/.env "
            "并填写 TELEGRAM_BOT_TOKEN（本项目不在 Attendance_system/.env 存 Token）。"
        )

    load_dotenv(_ATTENDANCE_ENV, override=False)
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("TG_BOT_TOKEN", None)
    load_dotenv(_GATEWAY_ENV, override=True)
    os.environ.setdefault("TG_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))

    raw = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not raw:
        raise RuntimeError("bot_gateway/.env 中未设置 TELEGRAM_BOT_TOKEN")

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(f"https://api.telegram.org/bot{raw}/getMe")
            data = resp.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"无法校验 Bot Token: {e}") from e

    if not data.get("ok"):
        raise RuntimeError(f"Bot Token 无效: {data.get('description', data)}")

    bot_id = int(data["result"]["id"])
    if bot_id in _FORBIDDEN_BOT_IDS:
        raise RuntimeError(
            f"bot_gateway/.env 中的 Token 属于已禁用的历史 Bot（id={bot_id}）。"
            "请在本项目使用独立测试 Bot 的 Token。"
        )
    return bot_id
