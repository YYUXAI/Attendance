#!/usr/bin/env python3
"""重跑 YYMG 工号打卡群日志中的全部打卡截图（去重后）。"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

os.environ.setdefault("CHECKIN_REMOTE_DIFF_DESKTOP_FALLBACK", "true")

LOG_PATH = ROOT / "logs" / "attendance-main.log"
CHAT_ID = "-1004496944161"
DAY_PREFIX = os.getenv("REPLAY_DAY_PREFIX", "2026-06-28")

pat_dl = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*image downloaded file_id=(\S+) sha256=([a-f0-9]+)"
)
pat_remote = re.compile(rf"remote_diff mode chat_id={re.escape(CHAT_ID)}.*tg_id=(\d+)")
pat_fail = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*"
    r"(?:remote_validate_failed|handler_rejected).*tg_id=(\d+).*error=([A-Z_]+)"
)
pat_ok = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*stage=remote_validated_ok tg_id=(\d+)"
)
pat_saved = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*stage=saved tg_id=(\d+) employee_id=(\S+)"
)


def collect_samples() -> list[dict]:
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    by_sha: OrderedDict[str, dict] = OrderedDict()

    for i, line in enumerate(lines):
        m = pat_remote.search(line)
        if not m:
            continue
        tg_id = int(m.group(1))
        ts_line = line.split(" INFO ")[0] if " INFO " in line else ""
        if DAY_PREFIX and not ts_line.startswith(DAY_PREFIX):
            continue

        fid = sha = dl_ts = None
        for j in range(i - 1, max(i - 10, -1), -1):
            md = pat_dl.search(lines[j])
            if md:
                dl_ts, fid, sha = md.group(1), md.group(2), md.group(3)
                break
        if not fid or not sha:
            continue

        log_error: str | None = None
        log_ok = False
        employee_id = None
        for k in range(i, min(i + 80, len(lines))):
            if pat_ok.search(lines[k]) and f"tg_id={tg_id}" in lines[k]:
                log_ok = True
            ms = pat_saved.search(lines[k])
            if ms and int(ms.group(2)) == tg_id:
                log_ok = True
                employee_id = ms.group(3)
            mf = pat_fail.search(lines[k])
            if mf and int(mf.group(2)) == tg_id:
                log_error = mf.group(3)
                if "handler_rejected" in lines[k]:
                    break
            if "remote_validate_failed" in lines[k] and f"tg_id={tg_id}" in lines[k]:
                mf2 = re.search(r"error=([A-Z_]+)", lines[k])
                if mf2:
                    log_error = mf2.group(1)

        if sha not in by_sha:
            by_sha[sha] = {
                "dl_ts": dl_ts,
                "tg_id": tg_id,
                "file_id": fid,
                "sha256": sha[:16],
                "log_ok": log_ok,
                "log_error": log_error,
                "employee_id": employee_id,
            }
    return list(by_sha.values())


async def replay_one(sample: dict) -> dict:
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
    t0 = time.perf_counter()

    remote, ai_err = await extract_remote_checkin_from_zhipu(
        image_bytes=image_bytes,
        config=cfg,
        tg_id=sample["tg_id"],
        reference_utc=ref_utc,
        shift_timezone="Asia/Shanghai",
    )
    sec = round(time.perf_counter() - t0, 1)

    if ai_err:
        return {
            **sample,
            "ok": False,
            "new_error": ai_err.error_code,
            "clock_time": None,
            "clock_date": None,
            "desktop_id": None,
            "folder": False,
            "sec": sec,
        }
    if remote is None:
        return {
            **sample,
            "ok": False,
            "new_error": "AI_EXTRACT_FAILED",
            "clock_time": None,
            "clock_date": None,
            "desktop_id": None,
            "folder": False,
            "sec": sec,
        }

    ext = remote.extraction
    reg = get_by_tg_id(sample["tg_id"])
    validated = validate_remote_extraction_for_checkin(
        remote=remote,
        reg=reg,
        shift_timezone="Asia/Shanghai",
        now_utc=ref_utc,
        max_skew_minutes=cfg.max_clock_skew_minutes,
    )
    base = {
        **sample,
        "clock_time": ext.clock_time,
        "clock_date": ext.clock_date,
        "desktop_id": remote.desktop_employee_id,
        "folder": remote.has_green_person_folder,
        "sec": sec,
        "reg_employee_id": getattr(reg, "employee_id", None) if reg else None,
    }
    if hasattr(validated, "ok"):
        return {**base, "ok": False, "new_error": validated.error_code}
    local = validated.astimezone(ZoneInfo("Asia/Shanghai"))
    return {
        **base,
        "ok": True,
        "new_error": None,
        "clock_local": local.strftime("%H:%M:%S"),
    }


async def main() -> None:
    samples = collect_samples()
    print(f"=== YYMG 群 {DAY_PREFIX or '全部'} 去重后 {len(samples)} 张 ===")
    if not samples:
        return

    results: list[dict] = []
    for idx, sample in enumerate(samples, 1):
        result = await replay_one(sample)
        results.append(result)
        status = "PASS" if result["ok"] else f"FAIL({result['new_error']})"
        log_tag = "log_ok" if result["log_ok"] else f"log_fail({result.get('log_error')})"
        changed = (
            "SAME"
            if (result["ok"] and result["log_ok"])
            or (not result["ok"] and not result["log_ok"])
            else "CHANGED"
        )
        print(
            f"[{idx}/{len(samples)}] tg={result['tg_id']} emp={result.get('reg_employee_id')} "
            f"sha={result['sha256']} | now {status} time={result.get('clock_time')} "
            f"date={result.get('clock_date')} id={result.get('desktop_id')} folder={result.get('folder')} "
            f"| was {log_tag} | {changed} | {result['sec']}s"
        )

    ok_n = sum(1 for r in results if r["ok"])
    log_ok_n = sum(1 for r in results if r["log_ok"])
    fixed = sum(1 for r in results if r["ok"] and not r["log_ok"])
    regressed = sum(1 for r in results if not r["ok"] and r["log_ok"])
    same = sum(
        1
        for r in results
        if (r["ok"] and r["log_ok"]) or (not r["ok"] and not r["log_ok"])
    )

    print("=== SUMMARY ===")
    print(f"replay pass: {ok_n}/{len(results)}")
    print(f"log pass:    {log_ok_n}/{len(results)}")
    print(f"fixed:       {fixed} (当时失败 → 现在通过)")
    print(f"regressed:   {regressed} (当时通过 → 现在失败)")
    print(f"same outcome:{same}/{len(results)}")

    fails = [r for r in results if not r["ok"]]
    if fails:
        print("=== STILL FAIL ===")
        by_err: dict[str, int] = {}
        for r in fails:
            e = r["new_error"] or "UNKNOWN"
            by_err[e] = by_err.get(e, 0) + 1
        for e, n in sorted(by_err.items(), key=lambda x: -x[1]):
            print(f"  {e}: {n}")


if __name__ == "__main__":
    asyncio.run(main())
