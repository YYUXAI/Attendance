# -*- coding: utf-8 -*-
"""手动触发：工号打卡群当月考勤同步到 Google 表。"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")


async def main() -> int:
    from infra.checkin_remote_diff_config import remote_diff_chat_ids
    from services.remote_diff_google_sheets_export_service import (
        sync_remote_diff_group_month_to_google_sheets,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chat-id",
        type=int,
        default=0,
        help="工号打卡群 chat_id；默认取 CHECKIN_REMOTE_DIFF_CHAT_IDS 第一个",
    )
    args = parser.parse_args()

    chat_id = args.chat_id
    if not chat_id:
        ids = sorted(remote_diff_chat_ids())
        if not ids:
            print("未配置 CHECKIN_REMOTE_DIFF_CHAT_IDS")
            return 1
        chat_id = ids[0]

    result = await sync_remote_diff_group_month_to_google_sheets(chat_id=int(chat_id), bot=None)
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
