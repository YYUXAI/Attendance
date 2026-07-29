"""重发指定群、指定日期的「今日考勤概览」，可选删除旧消息。"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from aiogram import Bot

from infra.bbq_google_sheets_config import DEFAULT_BBQ_CHAT_ID
from infra.bot import build_app
from services import group_attendance_summary_service


def _parse_date(raw: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid date: {raw!r}")


async def _find_summary_message_id(
    *,
    bot: Bot,
    chat_id: int,
    probe_admin_chat_id: int,
    title_snippet: str,
    search_from: int,
    search_to: int,
) -> int | None:
    """通过 forward 到管理员私聊读取正文，定位 Bot 发的概览 message_id。"""
    for mid in range(search_from, search_to + 1):
        try:
            forwarded = await bot.forward_message(
                chat_id=int(probe_admin_chat_id),
                from_chat_id=int(chat_id),
                message_id=int(mid),
                disable_notification=True,
            )
        except Exception:
            continue
        text = (forwarded.text or forwarded.caption or "").strip()
        try:
            await bot.delete_message(chat_id=int(probe_admin_chat_id), message_id=int(forwarded.message_id))
        except Exception:
            pass
        if title_snippet in text:
            return int(mid)
    return None


async def _run(
    *,
    chat_id: int,
    target_date: date,
    delete_message_id: int | None,
    find_delete: bool,
    probe_admin_chat_id: int | None,
) -> None:
    group_attendance_summary_service.ensure_tables()
    bot, _ = build_app()
    title_snippet = f"今日考勤概览-{target_date.strftime('%Y/%m/%d')}"
    try:
        if find_delete and delete_message_id is None:
            if probe_admin_chat_id is None:
                raise RuntimeError("find-delete requires --probe-admin-chat-id")
            probe = await bot.send_message(chat_id=int(chat_id), text=".")
            anchor = int(probe.message_id)
            try:
                await bot.delete_message(chat_id=int(chat_id), message_id=anchor)
            except Exception:
                pass
            delete_message_id = await _find_summary_message_id(
                bot=bot,
                chat_id=int(chat_id),
                probe_admin_chat_id=int(probe_admin_chat_id),
                title_snippet=title_snippet,
                search_from=max(1, anchor - 300),
                search_to=anchor - 1,
            )
            if delete_message_id is None:
                print(f"未找到含 {title_snippet!r} 的旧概览消息（搜索 {anchor - 300}..{anchor - 1}）")
            else:
                print(f"定位旧概览 message_id={delete_message_id}")

        if delete_message_id is not None:
            ok = await bot.delete_message(chat_id=int(chat_id), message_id=int(delete_message_id))
            print(f"deleted chat_id={chat_id} message_id={delete_message_id} ok={ok}")

        gname = await group_attendance_summary_service.resolve_group_display_name(
            bot=bot, chat_id=int(chat_id)
        )
        rows = group_attendance_summary_service.build_rows_for_group(
            chat_id=int(chat_id),
            target_date=target_date,
            group_name=gname,
        )
        text = group_attendance_summary_service.summarize_text(
            rows=rows, target_date=target_date, chat_id=int(chat_id)
        )
        msg = await bot.send_message(chat_id=int(chat_id), text=text)
        print(f"sent chat_id={chat_id} message_id={msg.message_id}")
        print("---")
        print(text)
    finally:
        await bot.session.close()


def main() -> None:
    p = argparse.ArgumentParser(description="重发群每日考勤概览")
    p.add_argument("--chat-id", type=int, default=int(DEFAULT_BBQ_CHAT_ID))
    p.add_argument("--date", required=True, help="YYYY-MM-DD 或 YYYY/MM/DD")
    p.add_argument("--delete-message-id", type=int, default=None)
    p.add_argument(
        "--find-delete",
        action="store_true",
        help="自动搜索并删除含当日标题的旧概览（需 --probe-admin-chat-id）",
    )
    p.add_argument(
        "--probe-admin-chat-id",
        type=int,
        default=None,
        help="用于 forward 探测的管理员 Telegram user id",
    )
    args = p.parse_args()
    asyncio.run(
        _run(
            chat_id=int(args.chat_id),
            target_date=_parse_date(args.date),
            delete_message_id=args.delete_message_id,
            find_delete=bool(args.find_delete),
            probe_admin_chat_id=args.probe_admin_chat_id,
        )
    )


if __name__ == "__main__":
    main()
