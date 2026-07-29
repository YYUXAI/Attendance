#!/usr/bin/env python3
"""重跑 remote_diff 日期/时间识别失败样本，统计正确率与稳定性。"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.getenv("ATTENDANCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

os.environ.setdefault("CHECKIN_REMOTE_DIFF_DESKTOP_FALLBACK", "true")

LOG_PATH = ROOT / "logs" / "attendance-main.log"
CHAT_ID = os.getenv("REPLAY_CHAT_ID", "-1004496944161")
DAY_PREFIX = os.getenv("REPLAY_DAY_PREFIX", "")  # 空=全部日期
ATTEMPTS = int(os.getenv("REPLAY_ATTEMPTS", "3"))

FAIL_CODES = {
    "AI_DATE_MISMATCH",
    "AI_TIME_SCREENSHOT_SKEW",
    "AI_TIME_NOT_FOUND",
    "AI_TIME_MISMATCH",
}

pat_dl = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*image downloaded file_id=(\S+) sha256=([a-f0-9]+)"
)
pat_remote = re.compile(rf"remote_diff mode chat_id={re.escape(CHAT_ID)}.*tg_id=(\d+)")
pat_fail = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*remote_validate_failed tg_id=(\d+) employee_id=(\S+) .*error=(\S+)"
)
pat_time = re.compile(r"ocr_time=([^ ]*)")
pat_date = re.compile(r"ocr_date=([^ ]*)")


def _clean_field(raw: str | None) -> str | None:
    if raw is None:
        return None
    val = raw.strip().strip("'")
    if val in ("None", "null", ""):
        return None
    return val


def collect_samples() -> list[dict]:
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    seen_sha: set[str] = set()
    samples: list[dict] = []

    for i, line in enumerate(lines):
        m = pat_fail.search(line)
        if not m:
            continue
        ts, tg_id, emp, err = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        if err not in FAIL_CODES:
            continue
        if DAY_PREFIX and not ts.startswith(DAY_PREFIX):
            continue

        old_time = _clean_field(pat_time.search(line).group(1) if pat_time.search(line) else None)
        old_date = _clean_field(pat_date.search(line).group(1) if pat_date.search(line) else None)

        fid = sha = dl_ts = None
        for j in range(i - 1, max(i - 80, -1), -1):
            mr = pat_remote.search(lines[j])
            if mr and int(mr.group(1)) == tg_id:
                for k in range(j - 1, max(j - 12, -1), -1):
                    md = pat_dl.search(lines[k])
                    if md:
                        dl_ts, fid, sha = md.group(1), md.group(2), md.group(3)
                        break
                break
        if not fid or not sha or sha in seen_sha:
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
                "old_date": old_date,
                "file_id": fid,
                "sha256": sha[:16],
            }
        )
    return samples


async def replay_one(sample: dict, *, attempts: int) -> dict:
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
    reg = get_by_tg_id(sample["tg_id"])

    attempt_rows: list[dict] = []
    for n in range(1, attempts + 1):
        remote, ai_err = await extract_remote_checkin_from_zhipu(
            image_bytes=image_bytes,
            config=cfg,
            tg_id=sample["tg_id"],
            reference_utc=ref_utc,
            shift_timezone="Asia/Shanghai",
        )
        if ai_err:
            attempt_rows.append(
                {"attempt": n, "ok": False, "error": ai_err.error_code, "time": None, "date": None}
            )
            continue
        if remote is None:
            attempt_rows.append(
                {"attempt": n, "ok": False, "error": "AI_EXTRACT_FAILED", "time": None, "date": None}
            )
            continue

        validated = validate_remote_extraction_for_checkin(
            remote=remote,
            reg=reg,
            shift_timezone="Asia/Shanghai",
            now_utc=ref_utc,
            max_skew_minutes=cfg.max_clock_skew_minutes,
        )
        t = remote.extraction.clock_time
        d = remote.extraction.clock_date
        if hasattr(validated, "ok"):
            attempt_rows.append({"attempt": n, "ok": False, "error": validated.error_code, "time": t, "date": d})
        else:
            local = validated.astimezone(ZoneInfo("Asia/Shanghai"))
            attempt_rows.append(
                {
                    "attempt": n,
                    "ok": True,
                    "error": None,
                    "time": t,
                    "date": d,
                    "clock_local": local.strftime("%H:%M:%S"),
                }
            )

    return {
        **sample,
        "attempts": attempt_rows,
        "any_ok": any(r["ok"] for r in attempt_rows),
        "all_ok": all(r["ok"] for r in attempt_rows),
    }


async def main() -> None:
    samples = collect_samples()
    print(f"=== unique date/time failures: {len(samples)} (chat={CHAT_ID}, day={DAY_PREFIX or 'all'}) ===")
    if not samples:
        return

    results: list[dict] = []
    for idx, sample in enumerate(samples, 1):
        print(
            f"[{idx}/{len(samples)}] emp={sample['employee_id']} sha={sample['sha256']} "
            f"was={sample['old_error']} ocr_time={sample['old_time']} ocr_date={sample['old_date']}",
            flush=True,
        )
        try:
            result = await replay_one(sample, attempts=ATTEMPTS)
        except Exception as exc:
            result = {**sample, "attempts": [], "any_ok": False, "all_ok": False, "download_error": str(exc)}
        results.append(result)

        if result.get("download_error"):
            print(f"  DOWNLOAD_FAIL: {result['download_error']}")
            continue
        for row in result["attempts"]:
            mark = "OK" if row["ok"] else f"FAIL({row['error']})"
            extra = f" clock={row['clock_local']}" if row.get("clock_local") else ""
            print(f"  try{row['attempt']}: {mark} time={row['time']} date={row['date']}{extra}")
        print(f"  => any_ok={result['any_ok']} all_ok={result['all_ok']}")

    dl_fail = sum(1 for r in results if r.get("download_error"))
    ok_any = sum(1 for r in results if r.get("any_ok"))
    ok_all = sum(1 for r in results if r.get("all_ok"))
    total_attempts = sum(len(r.get("attempts") or []) for r in results)
    pass_attempts = sum(sum(1 for a in (r.get("attempts") or []) if a["ok"]) for r in results)
    valid = len(results) - dl_fail

    print("\n=== SUMMARY ===")
    print(f"images: {len(results)} (download_fail={dl_fail})")
    print(f"image pass (any of {ATTEMPTS} tries): {ok_any}/{valid}")
    print(f"image pass (all {ATTEMPTS} tries):  {ok_all}/{valid}")
    print(f"attempt pass rate: {pass_attempts}/{total_attempts}")


if __name__ == "__main__":
    asyncio.run(main())
