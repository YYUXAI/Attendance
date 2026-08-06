#!/usr/bin/env python3
"""重跑 YYMG 群当日 remote_diff 时间不一致失败样本。"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

os.environ.setdefault("CHECKIN_REMOTE_DIFF_DESKTOP_FALLBACK", "true")

LOG_PATH = ROOT / "logs" / "attendance-main.log"
CHAT_ID = os.getenv("REPLAY_CHAT_ID", "0")
DAY_PREFIX = "2026-06-28"

pat_dl = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*image downloaded file_id=(\S+) sha256=([a-f0-9]+)"
)
pat_remote = re.compile(rf"remote_diff mode chat_id={re.escape(CHAT_ID)}.*tg_id=(\d+)")
pat_fail = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*remote_validate_failed tg_id=(\d+) employee_id=(\S+) .*error=(AI_TIME_[A-Z_]+)"
)
pat_time = re.compile(r"ocr_time=([^ ]*)")


def collect_samples() -> list[dict]:
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    seen_sha: set[str] = set()
    samples: list[dict] = []

    for i, line in enumerate(lines):
        m = pat_fail.search(line)
        if not m or not m.group(1).startswith(DAY_PREFIX):
            continue
        ts, tg_id, emp, err = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        tm = pat_time.search(line)
        old_time = tm.group(1) if tm else None
        if old_time in ("None", "null", ""):
            old_time = None
        else:
            old_time = old_time.strip("'")

        fid = sha = dl_ts = None
        for j in range(i - 1, max(i - 60, -1), -1):
            mr = pat_remote.search(lines[j])
            if mr and int(mr.group(1)) == tg_id:
                for k in range(j - 1, max(j - 8, -1), -1):
                    md = pat_dl.search(lines[k])
                    if md:
                        dl_ts, fid, sha = md.group(1), md.group(2), md.group(3)
                        break
                break
        if not fid or not sha:
            continue
        if sha in seen_sha:
            continue
        seen_sha.add(sha)
        samples.append(
            {
                "ts": ts,
                "dl_ts": dl_ts,
                "tg_id": tg_id,
                "employee_id": emp,
                "old_error": err,
                "old_time": old_time,
                "file_id": fid,
                "sha256": sha[:16],
            }
        )
    return samples


async def replay_one(sample: dict, *, attempts: int = 2) -> dict:
    from aiogram import Bot

    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id
    from services.checkin_remote_diff_service import (
        extract_remote_checkin_from_zhipu,
        validate_remote_extraction_for_checkin,
    )

    token = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    bot = Bot(token=token)
    try:
        tg_file = await bot.get_file(sample["file_id"])
        data = await bot.download_file(tg_file.file_path)
        image_bytes = data.read() if hasattr(data, "read") else bytes(data)
    finally:
        await bot.session.close()

    ref_utc = datetime.strptime(sample["dl_ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    cfg = load_checkin_ai_config()
    best: dict | None = None
    for attempt in range(1, attempts + 1):
        remote, ai_err = await extract_remote_checkin_from_zhipu(
            image_bytes=image_bytes,
            config=cfg,
            tg_id=sample["tg_id"],
            reference_utc=ref_utc,
            shift_timezone="Asia/Shanghai",
        )
        if ai_err:
            row = {**sample, "ok": False, "new_error": ai_err.error_code, "new_time": None, "attempt": attempt}
        elif remote is None:
            row = {**sample, "ok": False, "new_error": "AI_EXTRACT_FAILED", "new_time": None, "attempt": attempt}
        else:
            reg = get_by_tg_id(sample["tg_id"])
            validated = validate_remote_extraction_for_checkin(
                remote=remote,
                reg=reg,
                shift_timezone="Asia/Shanghai",
                now_utc=ref_utc,
                max_skew_minutes=cfg.max_clock_skew_minutes,
            )
            new_time = remote.extraction.clock_time
            if hasattr(validated, "ok"):
                row = {**sample, "ok": False, "new_error": validated.error_code, "new_time": new_time, "attempt": attempt}
            else:
                local = validated.astimezone(ZoneInfo("Asia/Shanghai"))
                row = {
                    **sample,
                    "ok": True,
                    "new_error": None,
                    "new_time": new_time,
                    "clock_local": local.strftime("%H:%M:%S"),
                    "attempt": attempt,
                }
        if row["ok"]:
            return row
        if best is None or (row.get("new_time") and not best.get("new_time")):
            best = row
    assert best is not None
    return best


async def main() -> None:
    samples = collect_samples()
    print(f"=== unique time failures: {len(samples)} ===")
    if not samples:
        return

    results: list[dict] = []
    for sample in samples:
        result = await replay_one(sample)
        results.append(result)
        status = "PASS" if result["ok"] else f"FAIL({result['new_error']})"
        print(
            f"emp={result['employee_id']} sha={result['sha256']} | "
            f"was {result['old_error']} time={result['old_time']} | "
            f"now {status} new_time={result.get('new_time')} clock={result.get('clock_local', '-')} "
            f"(try {result.get('attempt', 1)})"
        )

    ok_n = sum(1 for r in results if r["ok"])
    print(f"=== SUMMARY pass {ok_n}/{len(results)} ===")


if __name__ == "__main__":
    asyncio.run(main())
