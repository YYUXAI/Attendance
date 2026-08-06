#!/usr/bin/env python3
"""重跑 Y-UX-KQBBQ 群当月 AI 打卡失败样本，统计通过率。"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

BBQ_CHAT_ID = int(os.getenv("REPLAY_BBQ_CHAT_ID", "0"))
MONTH_PREFIX = os.getenv("REPLAY_MONTH_PREFIX", "2026-07")
LOG_SOURCE = os.getenv("REPLAY_LOG_PATH", "")
SSH_TARGET = os.getenv("REPLAY_SSH_TARGET", "")

AI_FAIL_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*validate_failed tg_id=(\d+) employee_id=(\S+) .*error=(\S+)"
)
PAT_DL = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*image downloaded file_id=(\S+) sha256=([a-f0-9]+)"
)
PAT_HANDLER = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*CHECKIN_HANDLER_ENTER.*tg_id=(\d+).*chat_id=(-?\d+)"
)
PAT_OCR = re.compile(r"ocr_name=([^ ]*) ocr_hint=([^ ]*) ocr_time=([^ ]*) ocr_date=([^ ]*)")
PAT_COMPOSITE = re.compile(r"composite=(True|False)")

AI_FAIL_CODES = {
    "AI_USER_MISMATCH",
    "AI_USER_OTHER_PERSON",
    "AI_USER_NOT_FOUND",
    "AI_NAME_NOT_FOUND",
    "AI_NOT_GROUNDED",
    "AI_TIME_SCREENSHOT_SKEW",
    "AI_TIME_NOT_FOUND",
    "AI_TIME_MISMATCH",
    "AI_DATE_MISMATCH",
    "AI_DATE_NOT_FOUND",
    "AI_COMPOSITE_SCREENSHOT",
    "AI_BOTH_MISSING",
}


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    v = s.strip().strip("'")
    return None if v in ("None", "null", "") else v


def fetch_log_lines() -> list[str]:
    if LOG_SOURCE:
        return Path(LOG_SOURCE).read_text(encoding="utf-8", errors="replace").splitlines()
    if not SSH_TARGET:
        raise RuntimeError("REPLAY_SSH_TARGET is required when REPLAY_LOG_PATH is not set")
    cmd = [
        "ssh",
        "-i",
        os.path.expanduser("~/.ssh/nayxua_ed25519"),
        "-o",
        "ConnectTimeout=20",
        SSH_TARGET,
        "grep -E 'validate_failed|image downloaded|CHECKIN_HANDLER_ENTER' "
        f"~/Attendance/logs/attendance-main.log | grep '{MONTH_PREFIX}'",
    ]
    return subprocess.check_output(cmd, text=True).splitlines()


def collect_bbq_samples(lines: list[str]) -> list[dict]:
    seen_sha: set[str] = set()
    samples: list[dict] = []

    for i, line in enumerate(lines):
        m = AI_FAIL_RE.search(line)
        if not m:
            continue
        ts, tg_id_s, emp, err = m.group(1), m.group(2), m.group(3), m.group(4)
        if err not in AI_FAIL_CODES:
            continue
        if MONTH_PREFIX and not ts.startswith(MONTH_PREFIX):
            continue

        tg_id = int(tg_id_s)
        handler_idx = None
        for j in range(i - 1, -1, -1):
            h = PAT_HANDLER.search(lines[j])
            if not h:
                continue
            if int(h.group(2)) != tg_id:
                continue
            if int(h.group(3)) != BBQ_CHAT_ID:
                continue
            handler_idx = j
            break
        if handler_idx is None:
            continue

        fid = sha = dl_ts = None
        for k in range(handler_idx + 1, min(handler_idx + 25, len(lines))):
            if "validate_failed" in lines[k] and k != i:
                break
            md = PAT_DL.search(lines[k])
            if md:
                dl_ts, fid, sha = md.group(1), md.group(2), md.group(3)
                break
        if not fid or not sha or sha in seen_sha:
            continue
        seen_sha.add(sha)

        ocr_m = PAT_OCR.search(line)
        comp_m = PAT_COMPOSITE.search(line)
        samples.append(
            {
                "ts": ts,
                "dl_ts": dl_ts or ts,
                "tg_id": tg_id,
                "employee_id": emp,
                "old_error": err,
                "old_name": _clean(ocr_m.group(1) if ocr_m else None),
                "old_hint": _clean(ocr_m.group(2) if ocr_m else None),
                "old_time": _clean(ocr_m.group(3) if ocr_m else None),
                "old_date": _clean(ocr_m.group(4) if ocr_m else None),
                "composite": comp_m.group(1) == "True" if comp_m else False,
                "file_id": fid,
                "sha256": sha[:16],
            }
        )
    return samples


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
    from repositories.registrations_repo import get_by_tg_id
    from services import checkin_extraction_validate_service
    from services.checkin_image_ai_service import (
        _prepare_image_bytes,
        extract_checkin_from_image,
        is_composite_checkin_image,
    )

    reg = get_by_tg_id(sample["tg_id"])
    if reg is None:
        return {**sample, "replay": "SKIP", "new_error": "NOT_REGISTERED"}

    ref_utc = datetime.strptime(sample["dl_ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    image = await download(sample["file_id"])
    prepared = _prepare_image_bytes(image)
    composite = is_composite_checkin_image(raw_bytes=image, prepared_bytes=prepared) or sample["composite"]

    ext, ai_err = await extract_checkin_from_image(
        image_bytes=image,
        config=cfg,
        expected_tg_username=reg.tg_username,
        expected_english_name=reg.english_name,
        reference_utc=ref_utc,
        shift_timezone="Asia/Shanghai",
        tg_id=sample["tg_id"],
    )
    if ai_err is not None:
        return {
            **sample,
            "replay": "FAIL",
            "new_error": ai_err.error_code,
            "new_name": (ext.display_name or ext.username_hint) if ext else None,
            "new_time": ext.clock_time if ext else None,
        }
    if ext is None:
        return {**sample, "replay": "FAIL", "new_error": "AI_EXTRACT_FAILED", "new_name": None, "new_time": None}

    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Shanghai",
        now_utc=ref_utc,
        max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
        composite_screenshot=composite,
    )
    if hasattr(val, "ok") and not val.ok:
        return {
            **sample,
            "replay": "FAIL",
            "new_error": val.error_code,
            "new_name": ext.display_name or ext.username_hint,
            "new_time": ext.clock_time,
        }
    return {
        **sample,
        "replay": "PASS",
        "new_error": None,
        "new_name": ext.display_name or ext.username_hint,
        "new_time": ext.clock_time,
    }


async def main() -> None:
    lines = fetch_log_lines()
    samples = collect_bbq_samples(lines)
    if not samples:
        print(f"no BBQ samples for month={MONTH_PREFIX} chat_id={BBQ_CHAT_ID}")
        return

    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    print(f"group=Y-UX-KQBBQ chat_id={BBQ_CHAT_ID} month={MONTH_PREFIX}")
    print(f"model={cfg.model} unique_failed_images={len(samples)}")
    print("-" * 80)

    results: list[dict] = []
    for idx, sample in enumerate(samples, 1):
        r = await replay_one(sample, cfg=cfg)
        results.append(r)
        flag = {"PASS": "✅", "SKIP": "⏭", "FAIL": "❌"}.get(r["replay"], "?")
        print(
            f"[{idx}/{len(samples)}] {flag} {r['ts'][:16]} emp={r['employee_id']} "
            f"old={r['old_error']} -> {r['replay']}"
            + (f" ({r['new_error']})" if r.get("new_error") else "")
        )

    passed = sum(1 for r in results if r["replay"] == "PASS")
    failed = sum(1 for r in results if r["replay"] == "FAIL")
    skipped = sum(1 for r in results if r["replay"] == "SKIP")
    tested = passed + failed
    print("-" * 80)
    print(f"去重失败图: {len(samples)} 张")
    print(f"可测: {tested} | 通过: {passed} | 仍失败: {failed} | 跳过(无登记): {skipped}")
    if tested:
        print(f"通过率: {passed}/{tested} = {100 * passed / tested:.1f}%")

    by_old: dict[str, list[str]] = {}
    for r in results:
        by_old.setdefault(r["old_error"], []).append(r["replay"])
    print("\n按原失败码:")
    for code, flags in sorted(by_old.items()):
        p = sum(1 for f in flags if f == "PASS")
        print(f"  {code}: {p}/{len(flags)} 通过")


if __name__ == "__main__":
    asyncio.run(main())
