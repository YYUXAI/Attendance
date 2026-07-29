#!/usr/bin/env python3
"""重跑 Y-UX-KQBBQ 群当月全部打卡截图（成功+失败），统计当前通过率。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv("ATTENDANCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

BBQ_CHAT_ID = int(os.getenv("REPLAY_BBQ_CHAT_ID", "-1003883297177"))
MONTH_PREFIX = os.getenv("REPLAY_MONTH_PREFIX", "2026-07")
# 可选：按北京日过滤，如 REPLAY_BJ_FROM=2026-07-06 REPLAY_BJ_TO=2026-07-11
_BJ_FROM = os.getenv("REPLAY_BJ_FROM", "").strip()
_BJ_TO = os.getenv("REPLAY_BJ_TO", "").strip()
CONCURRENCY = int(os.getenv("REPLAY_CONCURRENCY", "2"))
LOG_PATH = Path(os.getenv("REPLAY_LOG_PATH", ROOT / "logs" / "attendance-main.log"))
_out_default = (
    f"replay_bbq_{_BJ_FROM}_{_BJ_TO}.jsonl"
    if _BJ_FROM and _BJ_TO
    else f"replay_bbq_{MONTH_PREFIX}_all.jsonl"
)
OUT_PATH = Path(os.getenv("REPLAY_OUT", ROOT / "logs" / _out_default))


def _bj_utc_window() -> tuple[datetime | None, datetime | None]:
    if not _BJ_FROM or not _BJ_TO:
        return None, None
    from zoneinfo import ZoneInfo

    bj = ZoneInfo("Asia/Shanghai")
    y1, m1, d1 = map(int, _BJ_FROM.split("-"))
    y2, m2, d2 = map(int, _BJ_TO.split("-"))
    start = datetime(y1, m1, d1, 0, 0, 0, tzinfo=bj).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime(y2, m2, d2, 23, 59, 59, tzinfo=bj).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


_WIN_START, _WIN_END = _bj_utc_window()

PAT_ENTER = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*CHECKIN_HANDLER_ENTER\] tg_id=(\d+).*chat_id=(-?\d+)"
)
PAT_DL = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*image downloaded file_id=(\S+) sha256=([a-f0-9]+)"
)
PAT_RETURN = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*CHECKIN_HANDLER_RETURN\] tg_id=(\d+) reason=(\S+)"
)
PAT_CODE = re.compile(r"code=(\S+)")


def collect_samples(lines: list[str]) -> list[dict]:
    seen: set[str] = set()
    samples: list[dict] = []
    for i, line in enumerate(lines):
        if not line.startswith(MONTH_PREFIX):
            continue
        m = PAT_ENTER.search(line)
        if not m:
            continue
        if int(m.group(3)) != BBQ_CHAT_ID:
            continue
        tg_id = int(m.group(2))
        ts = m.group(1)
        if _WIN_START is not None and _WIN_END is not None:
            ts_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            if not (_WIN_START <= ts_dt <= _WIN_END):
                continue
        fid = sha = None
        for k in range(i + 1, min(i + 40, len(lines))):
            if "CHECKIN_HANDLER_ENTER]" in lines[k]:
                break
            md = PAT_DL.search(lines[k])
            if md:
                fid, sha = md.group(2), md.group(3)
                break
        if not fid or not sha or sha in seen:
            continue
        reason = code = None
        for j in range(i + 1, min(i + 250, len(lines))):
            mr = PAT_RETURN.search(lines[j])
            if mr and int(mr.group(2)) == tg_id:
                reason = mr.group(3)
                mc = PAT_CODE.search(lines[j])
                code = mc.group(1) if mc else None
                break
        if reason == "no_matter_in_caption_skip":
            continue
        seen.add(sha)
        samples.append(
            {
                "ts": ts,
                "tg_id": tg_id,
                "file_id": fid,
                "sha256": sha[:16],
                "old_reason": reason,
                "old_code": code,
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


async def replay_one(sample: dict, *, cfg, sem: asyncio.Semaphore) -> dict:
    from repositories.registrations_repo import get_by_tg_id
    from services import checkin_extraction_validate_service
    from services.checkin_image_ai_service import (
        _prepare_image_bytes,
        extract_checkin_from_image,
        is_composite_checkin_image,
    )

    async with sem:
        reg = get_by_tg_id(sample["tg_id"])
        if reg is None:
            return {**sample, "replay": "SKIP", "new_error": "NOT_REGISTERED", "employee_id": None}

        ref_utc = datetime.strptime(sample["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        try:
            image = await download(sample["file_id"])
        except Exception as exc:
            return {
                **sample,
                "replay": "SKIP",
                "new_error": f"DOWNLOAD_FAILED:{type(exc).__name__}",
                "employee_id": reg.employee_id,
            }

        try:
            prepared = _prepare_image_bytes(image)
            composite = is_composite_checkin_image(raw_bytes=image, prepared_bytes=prepared)
            ext, ai_err = await extract_checkin_from_image(
                image_bytes=image,
                config=cfg,
                expected_tg_username=reg.tg_username,
                expected_english_name=reg.english_name,
                reference_utc=ref_utc,
                shift_timezone="Asia/Shanghai",
                tg_id=sample["tg_id"],
            )
            name = (ext.display_name or ext.username_hint) if ext else None
            clock = ext.clock_time if ext else None
            if ai_err is not None:
                return {
                    **sample,
                    "replay": "FAIL",
                    "new_error": ai_err.error_code,
                    "employee_id": reg.employee_id,
                    "new_name": name,
                    "new_time": clock,
                }
            if ext is None:
                return {
                    **sample,
                    "replay": "FAIL",
                    "new_error": "AI_EXTRACT_FAILED",
                    "employee_id": reg.employee_id,
                    "new_name": None,
                    "new_time": None,
                }
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
                    "employee_id": reg.employee_id,
                    "new_name": name,
                    "new_time": clock,
                }
            return {
                **sample,
                "replay": "PASS",
                "new_error": None,
                "employee_id": reg.employee_id,
                "new_name": name,
                "new_time": clock,
            }
        except Exception as exc:
            return {
                **sample,
                "replay": "FAIL",
                "new_error": f"EXCEPTION:{type(exc).__name__}",
                "employee_id": reg.employee_id,
            }


async def main() -> None:
    win = f" bj={_BJ_FROM}~{_BJ_TO} utc={_WIN_START}~{_WIN_END}" if _WIN_START else ""
    print(f"reading {LOG_PATH} month={MONTH_PREFIX} chat={BBQ_CHAT_ID}{win}")
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    # 只保留相关行，加速扫描
    useful = [
        l
        for l in lines
        if l.startswith(MONTH_PREFIX)
        and (
            "CHECKIN_HANDLER_ENTER]" in l
            or "image downloaded" in l
            or "CHECKIN_HANDLER_RETURN]" in l
        )
    ]
    samples = collect_samples(useful if useful else lines)
    print(f"unique BBQ images: {len(samples)} concurrency={CONCURRENCY}")
    print("old reasons:", Counter(s["old_reason"] for s in samples).most_common())

    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    print(f"model={cfg.model}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        OUT_PATH.unlink()

    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.perf_counter()
    done = 0
    results: list[dict] = []

    async def run_one(sample: dict) -> dict:
        nonlocal done
        r = await replay_one(sample, cfg=cfg, sem=sem)
        done += 1
        with OUT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if done % 20 == 0 or done == len(samples):
            elapsed = time.perf_counter() - t0
            rate = done / elapsed if elapsed else 0
            eta = (len(samples) - done) / rate if rate else 0
            print(
                f"[{done}/{len(samples)}] {r['replay']} "
                f"emp={r.get('employee_id')} err={r.get('new_error') or '-'} "
                f"elapsed={elapsed/60:.1f}m eta={eta/60:.1f}m",
                flush=True,
            )
        return r

    results = list(await asyncio.gather(*[run_one(s) for s in samples]))

    passed = sum(1 for r in results if r["replay"] == "PASS")
    failed = sum(1 for r in results if r["replay"] == "FAIL")
    skipped = sum(1 for r in results if r["replay"] == "SKIP")
    tested = passed + failed
    print("=" * 72)
    print(f"完成 {len(results)} | 可测 {tested} | 通过 {passed} | 失败 {failed} | 跳过 {skipped}")
    if tested:
        print(f"通过率: {passed}/{tested} = {100 * passed / tested:.1f}%")
    print("失败码:", dict(Counter(r["new_error"] for r in results if r["replay"] == "FAIL")))
    print("跳过码:", dict(Counter(r["new_error"] for r in results if r["replay"] == "SKIP")))

    regressed = [
        r
        for r in results
        if r["old_reason"] in {"success_silent", "ai_dry_run_success"} and r["replay"] == "FAIL"
    ]
    recovered = [
        r for r in results if r["old_reason"] == "ai_failed_replied" and r["replay"] == "PASS"
    ]
    still_fail = [
        r for r in results if r["old_reason"] == "ai_failed_replied" and r["replay"] == "FAIL"
    ]
    print(f"原成功→现失败(回归): {len(regressed)}")
    print(f"原失败→现通过(修复): {len(recovered)}")
    print(f"原失败→仍失败: {len(still_fail)}")
    if regressed:
        print("回归样例:")
        for r in regressed[:15]:
            print(
                f"  {r['ts']} emp={r.get('employee_id')} "
                f"err={r['new_error']} name={r.get('new_name')!r} sha={r['sha256']}"
            )
    if still_fail:
        print("仍失败样例:")
        for r in still_fail[:15]:
            print(
                f"  {r['ts']} emp={r.get('employee_id')} "
                f"old={r.get('old_code')} now={r['new_error']} sha={r['sha256']}"
            )
    print(f"明细: {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
