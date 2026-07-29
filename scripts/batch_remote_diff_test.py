#!/usr/bin/env python3
"""批量用群内历史打卡图跑 remote_diff 识别，统计成功率。"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

# 工号打卡群 2026-06-26 日志中提取的去重 file_id（按 sha256 去重）
SAMPLES: list[tuple[str, str, str | None]] = [
    # (label, file_id, log_expected_error or None for OK)
    ("57c54617", "AgACAgUAAxkBAAIJVWo-QJsZp-vUVmj6bezOjTt9tqhOAAJgD2sb3t7xVWGaZUlA1LkvAQADAgADeQADPAQ", None),
    ("9aafe3d3", "AgACAgUAAxkBAAIJWWo-QNHBqjXC5IyFNFWtsthctMojAAJhD2sb3t7xVaq9GP0pnho6AQADAgADeQADPAQ", "REMOTE_EMPLOYEE_ID_NOT_FOUND"),
    ("568c7084", "AgACAgUAAxkBAAIJW2o-QPPIiO2_1ux0V1TQydLIpuRAAAJiD2sb3t7xVaRiEqsUCQzwAQADAgADeQADPAQ", "REMOTE_EMPLOYEE_ID_MISMATCH"),
    ("ffa38629", "AgACAgUAAxkBAAIJX2o-QRfpk_rlg4_I6PERKhUx-hHeAAJjD2sb3t7xVS1F7gAB1SMuRQEAAwIAA3kAAzwE", "REMOTE_EMPLOYEE_ID_NOT_FOUND"),
    ("50c4b56c", "AgACAgUAAxkBAAIJZGo-Q0RYQwXhCpx94owbGF6eDGZWAAJmD2sb3t7xVa7qjI9HfpUfAQADAgADeQADPAQ", "REMOTE_EMPLOYEE_ID_NOT_FOUND"),
    ("a374cd3c", "AgACAgUAAxkBAAIJZmo-Q3PChi98FFEyvMGts4ASVuF1AAJnD2sb3t7xVWQ-oAm1P-5pAQADAgADeQADPAQ", None),
    ("65cf6c70", "AgACAgUAAxkBAAIJamo-Q5fNRtsoaJE7JXvJwGxYvqM6AAJoD2sb3t7xVfcP2-fVle8RAQADAgADeQADPAQ", None),
    ("d7ff1401", "AgACAgUAAxkBAAIJbmo-Q8Wepg2dey9yAa8UTvHkXjrmAAJqD2sb3t7xVVhD4QNx64laAQADAgADeQADPAQ", "REMOTE_EMPLOYEE_ID_NOT_FOUND"),
]

EXPECTED_EMPLOYEE_ID = "99999"
TG_ID = 1302377984


async def _download(file_id: str) -> bytes | None:
    from aiogram import Bot

    token = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("ERROR: BOT_TOKEN missing")
        return None
    bot = Bot(token=token)
    try:
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            return None
        data = await bot.download_file(tg_file.file_path)
        if data is None:
            return None
        return data.read() if hasattr(data, "read") else bytes(data)
    finally:
        await bot.session.close()


async def _run_one(label: str, file_id: str, log_expected: str | None) -> dict:
    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id
    from services.checkin_remote_diff_service import (
        extract_remote_checkin_from_zhipu,
        validate_remote_extraction_for_checkin,
    )

    t0 = time.perf_counter()
    image_bytes = await _download(file_id)
    if not image_bytes:
        return {
            "label": label,
            "ok": False,
            "error": "DOWNLOAD_FAILED",
            "sec": time.perf_counter() - t0,
            "log_expected": log_expected,
            "match_log": False,
        }

    cfg = load_checkin_ai_config()
    now = datetime.now(timezone.utc)
    remote, ai_err = await extract_remote_checkin_from_zhipu(
        image_bytes=image_bytes,
        config=cfg,
        tg_id=TG_ID,
        reference_utc=now,
        shift_timezone="Asia/Shanghai",
    )
    if ai_err is not None:
        err = ai_err.error_code
        desktop_id = None
        folder = None
    elif remote is None:
        err = "AI_EXTRACT_FAILED"
        desktop_id = None
        folder = None
    else:
        reg = get_by_tg_id(TG_ID)
        validated = validate_remote_extraction_for_checkin(
            remote=remote,
            reg=reg,
            shift_timezone="Asia/Shanghai",
            now_utc=now,
            max_skew_minutes=cfg.max_clock_skew_minutes,
        )
        desktop_id = remote.desktop_employee_id
        folder = remote.has_green_person_folder
        if hasattr(validated, "ok"):
            err = validated.error_code
        else:
            err = None

    ok = err is None
    log_err = log_expected
    match_log = (ok and log_err is None) or (not ok and err == log_err)
    return {
        "label": label,
        "ok": ok,
        "error": err,
        "desktop_id": desktop_id,
        "folder": folder,
        "sec": round(time.perf_counter() - t0, 1),
        "log_expected": log_expected,
        "match_log": match_log,
    }


async def main() -> None:
    os.environ.setdefault("CHECKIN_REMOTE_DIFF_DESKTOP_FALLBACK", "true")
    print(f"fallback={os.getenv('CHECKIN_REMOTE_DIFF_DESKTOP_FALLBACK')}")
    print(f"samples={len(SAMPLES)} expected_employee_id={EXPECTED_EMPLOYEE_ID}")
    print("-" * 72)
    results = []
    for label, file_id, log_expected in SAMPLES:
        r = await _run_one(label, file_id, log_expected)
        results.append(r)
        status = "PASS" if r["ok"] else f"FAIL({r['error']})"
        log_tag = "log_match" if r["match_log"] else "log_diff"
        print(
            f"{r['label']}\t{status}\tid={r.get('desktop_id')}\tfolder={r.get('folder')}\t"
            f"{r['sec']}s\t{log_tag}\tlog_was={log_expected or 'OK'}"
        )

    ok_n = sum(1 for r in results if r["ok"])
    match_n = sum(1 for r in results if r["match_log"])
    print("-" * 72)
    print(f"success_rate: {ok_n}/{len(results)} = {100*ok_n/len(results):.1f}%")
    print(f"same_as_log:  {match_n}/{len(results)} = {100*match_n/len(results):.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
