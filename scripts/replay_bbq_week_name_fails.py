#!/usr/bin/env python3
"""重跑本周 BBQ 姓名类问题样本。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv("ATTENDANCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")
logging.disable(logging.WARNING)

TARGETS = Path(
    os.getenv(
        "REPLAY_NAME_TARGETS",
        ROOT / "logs" / "replay_bbq_week_name_targets.json",
    )
)
OUT_PATH = Path(
    os.getenv(
        "REPLAY_NAME_OUT",
        ROOT / "logs" / "replay_bbq_week_name_rerun.jsonl",
    )
)


async def download(file_id: str) -> bytes:
    from aiogram import Bot

    token = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    bot = Bot(token=token)
    try:
        tg_file = await bot.get_file(file_id)
        data = await bot.download_file(tg_file.file_path)
        return data.read() if hasattr(data, "read") else bytes(data)
    finally:
        await bot.session.close()


async def replay_one(sample: dict, *, cfg) -> dict:
    from repositories.registrations_repo import get_by_employee_id, get_by_tg_id
    from services import checkin_extraction_validate_service
    from services.checkin_image_ai_service import (
        _prepare_image_bytes,
        extract_checkin_from_image,
        is_composite_checkin_image,
    )

    reg = None
    if sample.get("employee_id"):
        reg = get_by_employee_id(str(sample["employee_id"]))
    if reg is None and sample.get("tg_id"):
        reg = get_by_tg_id(int(sample["tg_id"]))

    base = {
        "ts": sample.get("ts"),
        "tg_id": sample.get("tg_id"),
        "employee_id": sample.get("employee_id") or (reg.employee_id if reg else None),
        "sha256": sample.get("sha256"),
        "old_reason": sample.get("old_reason"),
        "old_code": sample.get("old_code"),
        "prev_new": sample.get("new_error"),
    }
    if reg is None:
        return {**base, "replay": "SKIP", "new_error": "NOT_REGISTERED"}

    ref = datetime.strptime(sample["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    try:
        image = await download(sample["file_id"])
    except Exception as exc:
        return {**base, "replay": "SKIP", "new_error": f"DOWNLOAD:{type(exc).__name__}"}

    prepared = _prepare_image_bytes(image)
    composite = is_composite_checkin_image(raw_bytes=image, prepared_bytes=prepared)
    ext, err = await extract_checkin_from_image(
        image_bytes=image,
        config=cfg,
        expected_tg_username=reg.tg_username,
        expected_english_name=reg.english_name,
        reference_utc=ref,
        shift_timezone="Asia/Shanghai",
        tg_id=reg.tg_id,
    )
    name = (ext.display_name or ext.username_hint) if ext else None
    clock = ext.clock_time if ext else None
    date = ext.clock_date if ext else None
    if err is not None and ext is None:
        code = getattr(err, "error_code", None) or getattr(err, "code", "EXTRACT")
        return {
            **base,
            "replay": "FAIL",
            "new_error": code,
            "new_name": name,
            "new_time": clock,
            "new_date": date,
        }
    if ext is None:
        return {**base, "replay": "FAIL", "new_error": "AI_EXTRACT_FAILED", "new_name": None}

    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Shanghai",
        now_utc=ref,
        max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
        composite_screenshot=composite,
    )
    if hasattr(val, "ok") and not val.ok:
        return {
            **base,
            "replay": "FAIL",
            "new_error": val.error_code,
            "new_name": name,
            "new_time": clock,
            "new_date": date,
        }
    return {
        **base,
        "replay": "PASS",
        "new_error": None,
        "new_name": name,
        "new_time": clock,
        "new_date": date,
    }


async def main() -> None:
    from infra.checkin_ai_config import load_checkin_ai_config

    samples = json.loads(TARGETS.read_text(encoding="utf-8"))
    cfg = load_checkin_ai_config()
    print(f"model={cfg.model} samples={len(samples)} targets={TARGETS}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("", encoding="utf-8")

    results: list[dict] = []
    for i, sample in enumerate(samples, 1):
        row = await replay_one(sample, cfg=cfg)
        results.append(row)
        with OUT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        now = row.get("new_error") or "PASS"
        prev = row.get("prev_new") or row.get("old_code") or "-"
        print(
            f"[{i}/{len(samples)}] {row['replay']} emp={row.get('employee_id')} "
            f"prev={prev} now={now} name={row.get('new_name')!r}",
            flush=True,
        )

    passed = sum(1 for r in results if r["replay"] == "PASS")
    failed = sum(1 for r in results if r["replay"] == "FAIL")
    skipped = sum(1 for r in results if r["replay"] == "SKIP")
    print("=" * 60)
    print(f"完成 {len(results)} | 通过 {passed} | 失败 {failed} | 跳过 {skipped}")
    if results:
        print(f"通过率: {passed}/{len(results)} = {100 * passed / len(results):.0f}%")
    print("失败码:", dict(Counter(r["new_error"] for r in results if r["replay"] == "FAIL")))
    for r in results:
        mark = "OK" if r["replay"] == "PASS" else "NG"
        print(
            f"  {mark} {r['ts']} emp={r.get('employee_id')} "
            f"{r.get('old_code')}/{r.get('prev_new')} -> {r.get('new_error') or 'PASS'} "
            f"name={r.get('new_name')!r}"
        )
    print(f"明细: {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
