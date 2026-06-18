"""将本地图片设为 Telegram Bot 头像（setMyProfilePhoto）。

用法:
  python scripts/set_bot_profile_photo.py path/to/avatar.png
  python scripts/set_bot_profile_photo.py assets/bot_avatar.jpg

说明:
  - 自动裁切为正方形并转为 JPG（Telegram 静态头像要求）
  - 也可在 @BotFather 里用 /setuserpic 手动上传，无需本脚本
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _prepare_jpeg_bytes(path: Path, *, size: int = 512) -> bytes:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    if side != size:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


async def set_profile_photo(*, token: str, image_path: Path) -> dict:
    jpeg = _prepare_jpeg_bytes(image_path)
    meta = json.dumps({"type": "static", "photo": "attach://avatar"})
    form = aiohttp.FormData()
    form.add_field("photo", meta, content_type="application/json")
    form.add_field(
        "avatar",
        jpeg,
        filename="avatar.jpg",
        content_type="image/jpeg",
    )
    url = f"https://api.telegram.org/bot{token}/setMyProfilePhoto"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            return await resp.json(content_type=None)


def main() -> None:
    load_dotenv(_ROOT / ".env", override=True, encoding="utf-8")
    parser = argparse.ArgumentParser(description="设置 Telegram Bot 头像")
    parser.add_argument("image", type=Path, help="头像图片路径（PNG/JPG 均可）")
    args = parser.parse_args()
    path = args.image.expanduser().resolve()
    if not path.is_file():
        print(f"文件不存在: {path}")
        sys.exit(1)
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("缺少 TELEGRAM_BOT_TOKEN（.env）")
        sys.exit(1)
    data = asyncio.run(set_profile_photo(token=token, image_path=path))
    if data.get("ok"):
        print("头像设置成功")
        return
    print("设置失败:", data.get("description") or data)
    sys.exit(1)


if __name__ == "__main__":
    main()
