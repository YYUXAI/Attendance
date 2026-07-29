#!/usr/bin/env python3
"""手动：测试群 Google 同步。"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="测试群 Google 同步")
    parser.add_argument(
        "--chat-id",
        type=int,
        default=-5217289694,
        help="测试群 chat_id（默认 -5217289694）",
    )
    parser.add_argument(
        "--shift-only",
        action="store_true",
        help="仅同步班表来源 Google 表 → 本地数据库",
    )
    args = parser.parse_args()

    if args.shift_only:
        from services.test_group_google_sheets_service import sync_test_group_shifts_from_google

        result = sync_test_group_shifts_from_google()
        print(result.message)
        raise SystemExit(0 if result.ok else 1)

    from services.test_group_google_sheets_service import sync_test_group_month_to_google_sheets

    result = await sync_test_group_month_to_google_sheets(chat_id=int(args.chat_id), bot=None)
    print(result.message)
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
