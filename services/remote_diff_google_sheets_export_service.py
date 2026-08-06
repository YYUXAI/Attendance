"""工号打卡群 Google 考勤回写已停用：考勤表仅由测试群同步（见 test_group_google_sheets_service）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteDiffSheetsSyncResult:
    ok: bool
    message: str
    row_count: int = 0
    sheet_title: str = ""


async def sync_remote_diff_group_month_to_google_sheets(
    *,
    chat_id: int,
    bot: Bot | None = None,
    cfg: object | None = None,
) -> RemoteDiffSheetsSyncResult:
    return RemoteDiffSheetsSyncResult(
        False,
        f"chat_id={chat_id} 工号群不回写 Google 考勤表（仅测试群打卡记录同步）",
    )


def schedule_remote_diff_sheets_sync_after_checkin(*, bot: Bot, chat_id: int) -> None:
    """工号打卡群不回写 Google 表；考勤回写由测试群 schedule_test_group_sheets_sync_after_checkin 处理。"""
    del bot, chat_id
