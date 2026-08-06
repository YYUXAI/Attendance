#!/usr/bin/env python3
"""重跑近期 AI 打卡失败样本，统计当前通过率。"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

DAY_PREFIX = os.getenv("REPLAY_DAY_PREFIX", "2026-07-10")
LOG_SOURCE = os.getenv("REPLAY_LOG_PATH", "")

AI_FAIL_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*"
    r"(?:remote_)?validate_failed tg_id=(\d+) employee_id=(\S+) .*error=(\S+)"
)
PAT_DL = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*image downloaded file_id=(\S+) sha256=([a-f0-9]+)"
)
PAT_HANDLER = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*CHECKIN_HANDLER_ENTER.*tg_id=(\d+)"
)
PAT_REMOTE = re.compile(r"remote_diff mode chat_id=")
PAT_OCR = re.compile(r"ocr_name=([^ ]*) ocr_hint=([^ ]*) ocr_time=([^ ]*) ocr_date=([^ ]*)")
PAT_EXPECT = re.compile(r"expected_user='([^']*)' expected_name='([^']*)'")

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


def collect_samples(lines: list[str]) -> list[dict]:
    seen_sha: set[str] = set()
    samples: list[dict] = []

    for i, line in enumerate(lines):
        m = AI_FAIL_RE.search(line)
        if not m:
            continue
        ts, tg_id_s, emp, err = m.group(1), m.group(2), m.group(3), m.group(4)
        if err not in AI_FAIL_CODES:
            continue
        if DAY_PREFIX and not ts.startswith(DAY_PREFIX):
            continue

        tg_id = int(tg_id_s)
        ocr_m = PAT_OCR.search(line)
        exp_m = PAT_EXPECT.search(line)
        is_remote = "remote_validate_failed" in line

        fid = sha = dl_ts = None
        handler_idx = None
        for j in range(i - 1, max(i - 120, -1), -1):
            h = PAT_HANDLER.search(lines[j])
            if h and int(h.group(2)) == tg_id:
                handler_idx = j
                break
        if handler_idx is not None:
            for k in range(handler_idx + 1, min(handler_idx + 20, len(lines))):
                if not is_remote and PAT_REMOTE.search(lines[k]):
                    is_remote = True
                md = PAT_DL.search(lines[k])
                if md:
                    dl_ts, fid, sha = md.group(1), md.group(2), md.group(3)
                    break
        if not fid or not sha or sha in seen_sha:
            continue
        seen_sha.add(sha)

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
                "expected_user": _clean(exp_m.group(1) if exp_m else None),
                "expected_name": _clean(exp_m.group(2) if exp_m else None),
                "file_id": fid,
                "sha256": sha[:16],
                "remote": is_remote,
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
    from services.checkin_image_ai_service import extract_checkin_from_image

    reg = get_by_tg_id(sample["tg_id"])
    if reg is None:
        return {**sample, "replay": "SKIP", "new_error": "NOT_REGISTERED"}

    ref_utc = datetime.strptime(sample["dl_ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    shift_tz = "Asia/Shanghai"

    image = await download(sample["file_id"])

    if sample["remote"]:
        from services.checkin_remote_diff_service import (
            extract_remote_checkin_from_zhipu,
            validate_remote_extraction_for_checkin,
        )

        remote, ai_err = await extract_remote_checkin_from_zhipu(
            image_bytes=image,
            config=cfg,
            tg_id=sample["tg_id"],
        )
        if ai_err is not None:
            return {
                **sample,
                "replay": "FAIL",
                "new_error": ai_err.code,
                "new_name": None,
                "new_time": None,
            }
        val = validate_remote_extraction_for_checkin(
            remote=remote,
            reg=reg,
            shift_timezone=shift_tz,
            now_utc=ref_utc,
            max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
        )
        if hasattr(val, "ok") and not val.ok:
            return {
                **sample,
                "replay": "FAIL",
                "new_error": val.error_code,
                "new_name": remote.desktop_id if remote else None,
                "new_time": remote.clock_time if remote else None,
            }
        return {
            **sample,
            "replay": "PASS",
            "new_error": None,
            "new_name": remote.desktop_id if remote else None,
            "new_time": remote.clock_time if remote else None,
        }

    ext, ai_err = await extract_checkin_from_image(
        image_bytes=image,
        config=cfg,
        expected_tg_username=reg.tg_username,
        expected_english_name=reg.english_name,
        reference_utc=ref_utc,
        shift_timezone=shift_tz,
        tg_id=sample["tg_id"],
    )
    if ai_err is not None:
        return {
            **sample,
            "replay": "FAIL",
            "new_error": ai_err.code,
            "new_name": (ext.display_name or ext.username_hint) if ext else None,
            "new_time": ext.clock_time if ext else None,
        }
    if ext is None:
        return {**sample, "replay": "FAIL", "new_error": "AI_EXTRACT_FAILED", "new_name": None, "new_time": None}

    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone=shift_tz,
        now_utc=ref_utc,
        max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
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
    if LOG_SOURCE:
        log_text = Path(LOG_SOURCE).read_text(encoding="utf-8", errors="replace")
    else:
        import subprocess

        ssh_target = os.getenv("REPLAY_SSH_TARGET", "")
        if not ssh_target:
            raise RuntimeError("REPLAY_SSH_TARGET is required when LOG_SOURCE is not set")
        cmd = [
            "ssh",
            "-i",
            os.path.expanduser("~/.ssh/nayxua_ed25519"),
            "-o",
            "ConnectTimeout=15",
            ssh_target,
            f"grep -E 'validate_failed|remote_validate_failed|image downloaded|CHECKIN_HANDLER_ENTER|remote_diff mode' "
            f"~/Attendance/logs/attendance-main.log | grep '{DAY_PREFIX}'",
        ]
        log_text = subprocess.check_output(cmd, text=True)

    lines = log_text.splitlines()
    samples = collect_samples(lines)
    if not samples:
        print(f"no samples for prefix={DAY_PREFIX}")
        return

    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    print(f"model={cfg.model} samples={len(samples)} prefix={DAY_PREFIX}")
    print("-" * 72)

    results: list[dict] = []
    for idx, sample in enumerate(samples, 1):
        r = await replay_one(sample, cfg=cfg)
        results.append(r)
        flag = "✅" if r["replay"] == "PASS" else "❌"
        print(
            f"[{idx}/{len(samples)}] {flag} emp={r['employee_id']} sha={r['sha256']} "
            f"old={r['old_error']} -> {r['replay']}"
            + (f" ({r['new_error']})" if r.get("new_error") else "")
            + f" | name={r.get('old_name')!r}->{r.get('new_name')!r} "
            f"time={r.get('old_time')!r}->{r.get('new_time')!r}"
        )

    passed = sum(1 for r in results if r["replay"] == "PASS")
    total = len(results)
    print("-" * 72)
    print(f"通过率: {passed}/{total} = {100 * passed / total:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
