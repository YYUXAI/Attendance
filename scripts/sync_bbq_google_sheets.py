#!/usr/bin/env python3
"""手动：BBQ 群当月考勤 → Google 表 Y-UX-KQBBQ打卡记录。"""
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
    from infra.bbq_google_sheets_config import DEFAULT_BBQ_CHAT_ID, load_bbq_google_sheets_config
    from services.bbq_google_sheets_export_service import sync_bbq_group_month_to_google_sheets

    parser = argparse.ArgumentParser(description="BBQ 群 Google 考勤同步")
    parser.add_argument("--chat-id", type=int, default=DEFAULT_BBQ_CHAT_ID)
    args = parser.parse_args()

    cfg = load_bbq_google_sheets_config()
    result = await sync_bbq_group_month_to_google_sheets(chat_id=int(args.chat_id), bot=None, cfg=cfg)
    print(result.message)
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
