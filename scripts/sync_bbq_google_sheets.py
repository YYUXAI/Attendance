#!/usr/bin/env python3
"""手动：所有 active bbq-google-sheets 群当月考勤同步。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

async def main() -> None:
    from infra.bbq_google_sheets_config import load_bbq_google_sheets_config
    from repositories.attendance_runtime_config_repo import active_chat_ids_with_capability
    from services.bbq_google_sheets_export_service import sync_bbq_group_month_to_google_sheets

    cfg = load_bbq_google_sheets_config()
    chat_ids = active_chat_ids_with_capability(capability="bbq-google-sheets")
    if not chat_ids:
        print("没有 active bbq-google-sheets 群，无需同步")
        return
    failed = False
    for chat_id in chat_ids:
        result = await sync_bbq_group_month_to_google_sheets(chat_id=chat_id, cfg=cfg)
        print(result.message)
        failed = failed or not result.ok
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
