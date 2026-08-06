#!/usr/bin/env python3
"""重跑 KAIRICE 56753 两次姓名失败截图（2026-07-11 02:01/02:02）。"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from aiogram import Bot
from infra.checkin_ai_config import load_checkin_ai_config
from repositories.registrations_repo import get_by_tg_id
from services import checkin_extraction_validate_service, checkin_identity_match_service
from services.checkin_image_ai_service import extract_checkin_from_image

SAMPLES = [
    {
        "label": "fail1_0201",
        "file_id": "AgACAgUAAyEFAATndmmZAAIZpmpRM3D7R6J-bU-39arlkXRPUaAvAAIGFWsbp82JVuSeaGTdu5eRAQADAgADeQADPAQ",
        "expect_sha": "069e013410928b46",
        "old_name": "Y-UX-KQBQQ",
        "ref_utc": datetime(2026, 7, 10, 18, 1, 24, tzinfo=timezone.utc),
        "hist_raw": (
            '{"display_name":"Y-UX-KQBQQ","username_hint":"Y-UX-KQBQQ",'
            '"clock_time":"02:01:09","clock_date":"07-11","timezone_iana":null,"confidence":1}'
        ),
    },
    {
        "label": "fail2_0202",
        "file_id": "AgACAgUAAyEFAATndmmZAAIZsGpRM5ygffmd9tbBvDXgfEDG0BoDAAIIFWsbp82JVq7UF7dD0GNuAQADAgADeQADPAQ",
        "expect_sha": "18487545ee077f2a",
        "old_name": "Y-UX-KQBHQ",
        "ref_utc": datetime(2026, 7, 10, 18, 2, 9, tzinfo=timezone.utc),
        "hist_raw": (
            '{"display_name":"Y-UX-KQBHQ","username_hint":"Y-UX-KQBHQ",'
            '"clock_time":"02:01:57","clock_date":"07-11","timezone_iana":null,"confidence":1}'
        ),
    },
]

TG_ID = 7625966687
SHIFT_TZ = "Asia/Bangkok"


async def download(file_id: str) -> bytes:
    token = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    bot = Bot(token=token)
    try:
        tg_file = await bot.get_file(file_id)
        data = await bot.download_file(tg_file.file_path)
        return data.read() if hasattr(data, "read") else bytes(data)
    finally:
        await bot.session.close()


async def main() -> None:
    reg = get_by_tg_id(TG_ID)
    if reg is None:
        raise SystemExit("registration not found")
    cfg = load_checkin_ai_config()
    print(f"reg: {reg.employee_id} {reg.english_name} {reg.tg_username}")
    print(f"model: {cfg.model}")
    print("---")

    for sample in SAMPLES:
        print(f"=== {sample['label']} (当时失败: {sample['old_name']}) ===")
        image = await download(sample["file_id"])
        sha = hashlib.sha256(image).hexdigest()[:16]
        print(f"sha256: {sha} bytes={len(image)} match={sha == sample['expect_sha']}")

        present = checkin_identity_match_service.is_attendance_group_identity_noise(
            sample["old_name"], sample["old_name"].split("-")[-1]
        )
        resolved = checkin_identity_match_service.resolve_sender_identity_plan_b(
            display_name=sample["old_name"],
            username_hint=sample["old_name"].split("-")[-1],
            raw=sample["hist_raw"],
            tg_username=reg.tg_username,
            english_name=reg.english_name,
        )
        print(f"historical_planB: noise={present} resolved={resolved}")

        ext, err = await extract_checkin_from_image(
            image_bytes=image,
            config=cfg,
            expected_tg_username=reg.tg_username,
            expected_english_name=reg.english_name,
            reference_utc=sample["ref_utc"],
            shift_timezone=SHIFT_TZ,
            tg_id=TG_ID,
        )
        name = (ext.display_name or ext.username_hint) if ext else None
        print(
            f"rerun_extract: name={name!r} time={getattr(ext, 'clock_time', None)!r} "
            f"date={getattr(ext, 'clock_date', None)!r}"
        )
        if err:
            print(f"rerun_extract_err: {err.code}")

        if ext is not None:
            val = checkin_extraction_validate_service.validate_extraction_for_checkin(
                extraction=ext,
                reg=reg,
                shift_timezone=SHIFT_TZ,
                now_utc=sample["ref_utc"],
                max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
            )
            if hasattr(val, "ok"):
                print(f"rerun_validate: {'PASS' if val.ok else 'FAIL ' + str(val.error_code)}")
            else:
                print("rerun_validate: PASS")
        print()


if __name__ == "__main__":
    asyncio.run(main())
