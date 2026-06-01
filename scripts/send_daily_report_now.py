"""立即发送「群打卡汇总 CSV」（与每天 23:00 私聊那份相同）。当日已发过则跳过。"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from infra.bot import build_app
from services.daily_attendance_report_send import send_daily_attendance_report


async def main() -> None:
    force = "--force" in sys.argv
    bot, _dp = build_app()
    outcome = await send_daily_attendance_report(
        bot=bot,
        force=force,
        record_sent=not force,
    )
    print(outcome)
    await bot.session.close()
    if not outcome.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
