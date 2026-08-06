#!/usr/bin/env python3
"""重跑 YYMG 两张「上午+10:04」失败图，验证 ±12h 纠正。"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

import httpx

from infra.checkin_ai_config import load_checkin_ai_config
from repositories.registrations_repo import get_by_tg_id
from services.checkin_clock_time_service import resolve_remote_diff_clock_time
from services.checkin_remote_diff_service import (
    extract_remote_checkin_from_zhipu,
    validate_remote_extraction_for_checkin,
)

SAMPLES = [
    {
        "label": "campuchino",
        "emp": "46122",
        "tg_id": 6824160509,
        "file_id": "AgACAgUAAyEFAAMBDAnsIQACGa1qVPB6IgUgbBBV-y9M30iXINdMwAACZhZrG-r9qVbk4TWjBA0vigEAAwIAA3kAAzwE",
        "reference_utc": datetime(2026, 7, 13, 14, 4, 42, tzinfo=timezone.utc),
    },
    {
        "label": "oakrent",
        "emp": "74873",
        "tg_id": 8696824744,
        "file_id": "AgACAgUAAyEFAAMBDAnsIQACGa9qVPCFZjsOVlCxUQ6qWdyeXIX1awACZxZrG-r9qVagJIlhST0IcwEAAwIAA3kAAzwE",
        "reference_utc": datetime(2026, 7, 13, 14, 4, 54, tzinfo=timezone.utc),
    },
]


async def download(file_id: str) -> bytes:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        path = r.json()["result"]["file_path"]
        r2 = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
        r2.raise_for_status()
        return r2.content


async def main() -> None:
    cfg = load_checkin_ai_config()
    print("model", cfg.model, "skew", cfg.max_clock_skew_minutes)
    for s in SAMPLES:
        print("=" * 72)
        print("REPLAY", s["label"], s["emp"])
        img = await download(s["file_id"])
        print("bytes", len(img), "ref", s["reference_utc"].isoformat())

        demo = resolve_remote_diff_clock_time(
            clock_time="10:04",
            clock_period="上午",
            reference_utc=s["reference_utc"],
            shift_timezone="Asia/Shanghai",
            max_skew_minutes=int(cfg.max_clock_skew_minutes),
        )
        print("local resolve(10:04+上午) =>", demo)

        remote, ai_err = await extract_remote_checkin_from_zhipu(
            image_bytes=img,
            config=cfg,
            tg_id=s["tg_id"],
            reference_utc=s["reference_utc"],
            shift_timezone="Asia/Shanghai",
        )
        if ai_err is not None:
            print("AI_ERR", ai_err.error_code, ai_err.message)
            continue
        assert remote is not None
        ex = remote.extraction
        print(
            "extract clock=",
            ex.clock_time,
            "date=",
            ex.clock_date,
            "id=",
            remote.desktop_employee_id,
            "beijing=",
            remote.has_beijing_time,
        )
        # hint whether flip likely applied vs raw 10:xx
        if ex.clock_time and ex.clock_time.startswith("22:"):
            print("HIT: final clock is evening 22:xx (12h correction path likely)")
        elif ex.clock_time and ex.clock_time.startswith("10:"):
            print("MISS: final clock still 10:xx")

        reg = get_by_tg_id(int(s["tg_id"]))
        result = validate_remote_extraction_for_checkin(
            remote=remote,
            reg=reg,
            shift_timezone="Asia/Shanghai",
            now_utc=s["reference_utc"],
            max_skew_minutes=int(cfg.max_clock_skew_minutes),
        )
        if hasattr(result, "ok"):
            print("VALIDATE FAIL", result.error_code)
        else:
            print("VALIDATE OK", result)


if __name__ == "__main__":
    asyncio.run(main())
