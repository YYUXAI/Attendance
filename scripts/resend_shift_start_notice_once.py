"""向考勤群重发一条「开班考勤汇总」(shift 0) 样例，便于验收。不写入通知队列。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from infra.bot import build_app
from repositories import shifts_repo
from services.audit_service import build_shift_start_group_notice_html_for_shift

DEFAULT_GROUP_ID = -1003200046237
CANONICAL_SHIFT_ID = 0


async def _send(*, chat_id: int, text: str) -> int:
    bot, _ = build_app()
    try:
        msg = await bot.send_message(chat_id=int(chat_id), text=text, parse_mode="HTML")
        return int(msg.message_id)
    finally:
        await bot.session.close()


def main() -> None:
    shift_id = int(sys.argv[1]) if len(sys.argv) > 1 else CANONICAL_SHIFT_ID
    shift = shifts_repo.get_by_id(shift_id)
    chat_id = int(shift.attendance_group_id) if shift and shift.attendance_group_id else DEFAULT_GROUP_ID

    text = build_shift_start_group_notice_html_for_shift(shift_id=shift_id)
    if not text:
        print(f"无法生成 shift_id={shift_id} 的开班汇总正文")
        sys.exit(1)

    mid = asyncio.run(_send(chat_id=chat_id, text=text))
    print(f"已发送 shift_id={shift_id} 开班汇总到群 {chat_id}，message_id={mid}")


if __name__ == "__main__":
    main()
