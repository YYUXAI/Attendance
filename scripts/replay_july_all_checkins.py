#!/usr/bin/env python3
"""重跑 2026-07 全部打卡截图（BBQ + YYMG），统计当前通过率。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

MONTH_PREFIX = os.getenv("REPLAY_MONTH_PREFIX", "2026-07")
CONCURRENCY = int(os.getenv("REPLAY_CONCURRENCY", "2"))
OUT_PATH = Path(os.getenv("REPLAY_OUT", ROOT / "logs" / f"replay_{MONTH_PREFIX}_all.jsonl"))
BBQ_CHAT = "-1003883297177"
YYMG_CHAT = "-1004496944161"

PAT_ENTER = re.compile(r"CHECKIN_HANDLER_ENTER\] tg_id=(\d+).*chat_id=(-?\d+)")
PAT_DL = re.compile(r"image downloaded file_id=(\S+) sha256=([a-f0-9]+)")
PAT_RETURN = re.compile(r"CHECKIN_HANDLER_RETURN\] tg_id=(\d+) reason=(\S+)")
PAT_CODE = re.compile(r"code=(\S+)")
PAT_REMOTE = re.compile(r"remote_diff mode chat_id=")


def fetch_log_lines() -> list[str]:
    cmd = [
        "ssh",
        "-i",
        os.path.expanduser("~/.ssh/nayxua_ed25519"),
        "-o",
        "ConnectTimeout=20",
        "nayxua@139.162.47.196",
        "grep -E 'CHECKIN_HANDLER_ENTER|image downloaded|CHECKIN_HANDLER_RETURN|remote_diff mode' "
        f"~/Attendance/logs/attendance-main.log | grep '{MONTH_PREFIX}'",
    ]
    return subprocess.check_output(cmd, text=True).splitlines()


def collect_samples(lines: list[str]) -> list[dict]:
    seen: set[str] = set()
    samples: list[dict] = []
    for i, line in enumerate(lines):
        m = PAT_ENTER.search(line)
        if not m:
            continue
        tg_id = int(m.group(1))
        chat_id = m.group(2)
        ts = line[:19]
        fid = sha = None
        remote = chat_id == YYMG_CHAT
        for k in range(i + 1, min(i + 40, len(lines))):
            if "CHECKIN_HANDLER_ENTER]" in lines[k]:
                break
            if PAT_REMOTE.search(lines[k]):
                remote = True
            md = PAT_DL.search(lines[k])
            if md:
                fid, sha = md.group(1), md.group(2)
                break
        if not fid or not sha or sha in seen:
            continue
        reason = code = None
        for j in range(i + 1, min(i + 250, len(lines))):
            mr = PAT_RETURN.search(lines[j])
            if mr and int(mr.group(1)) == tg_id:
                reason = mr.group(2)
                mc = PAT_CODE.search(lines[j])
                code = mc.group(1) if mc else None
                break
        # 无配文跳过的不算有效打卡识图
        if reason == "no_matter_in_caption_skip":
            continue
        seen.add(sha)
        samples.append(
            {
                "ts": ts,
                "tg_id": tg_id,
                "chat_id": chat_id,
                "file_id": fid,
                "sha256": sha[:16],
                "remote": remote,
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

    async with sem:
        reg = get_by_tg_id(sample["tg_id"])
        if reg is None:
            return {**sample, "replay": "SKIP", "new_error": "NOT_REGISTERED"}

        ref_utc = datetime.strptime(sample["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        try:
            image = await download(sample["file_id"])
        except Exception as exc:
            return {**sample, "replay": "SKIP", "new_error": f"DOWNLOAD_FAILED:{type(exc).__name__}"}

        try:
            if sample["remote"]:
                from services.checkin_remote_diff_service import (
                    extract_remote_checkin_from_zhipu,
                    validate_remote_extraction_for_checkin,
                )

                remote, ai_err = await extract_remote_checkin_from_zhipu(
                    image_bytes=image,
                    config=cfg,
                    tg_id=sample["tg_id"],
                    reference_utc=ref_utc,
                    shift_timezone="Asia/Shanghai",
                )
                if ai_err is not None:
                    return {**sample, "replay": "FAIL", "new_error": ai_err.error_code}
                val = validate_remote_extraction_for_checkin(
                    remote=remote,
                    reg=reg,
                    shift_timezone="Asia/Shanghai",
                    now_utc=ref_utc,
                    max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
                )
                if hasattr(val, "ok") and not val.ok:
                    return {**sample, "replay": "FAIL", "new_error": val.error_code}
                return {**sample, "replay": "PASS", "new_error": None}

            from services import checkin_extraction_validate_service
            from services.checkin_image_ai_service import (
                _prepare_image_bytes,
                extract_checkin_from_image,
                is_composite_checkin_image,
            )

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
            if ai_err is not None:
                return {**sample, "replay": "FAIL", "new_error": ai_err.error_code}
            if ext is None:
                return {**sample, "replay": "FAIL", "new_error": "AI_EXTRACT_FAILED"}
            val = checkin_extraction_validate_service.validate_extraction_for_checkin(
                extraction=ext,
                reg=reg,
                shift_timezone="Asia/Shanghai",
                now_utc=ref_utc,
                max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
                composite_screenshot=composite,
            )
            if hasattr(val, "ok") and not val.ok:
                return {**sample, "replay": "FAIL", "new_error": val.error_code}
            return {**sample, "replay": "PASS", "new_error": None}
        except Exception as exc:
            return {**sample, "replay": "FAIL", "new_error": f"EXCEPTION:{type(exc).__name__}"}


def _print_summary(results: list[dict]) -> None:
    passed = sum(1 for r in results if r["replay"] == "PASS")
    failed = sum(1 for r in results if r["replay"] == "FAIL")
    skipped = sum(1 for r in results if r["replay"] == "SKIP")
    tested = passed + failed
    print("=" * 80)
    print(f"完成: {len(results)} | 可测: {tested} | 通过: {passed} | 失败: {failed} | 跳过: {skipped}")
    if tested:
        print(f"总通过率: {passed}/{tested} = {100 * passed / tested:.1f}%")

    for label, chat in (("BBQ Y-UX-KQBBQ", BBQ_CHAT), ("YYMG-DKQ-(NEW)", YYMG_CHAT)):
        sub = [r for r in results if r["chat_id"] == chat]
        if not sub:
            continue
        p = sum(1 for r in sub if r["replay"] == "PASS")
        f = sum(1 for r in sub if r["replay"] == "FAIL")
        t = p + f
        print(f"\n{label}: {p}/{t} = {100 * p / t:.1f}%" if t else f"\n{label}: no tested")
        errs = Counter(r["new_error"] for r in sub if r["replay"] == "FAIL")
        if errs:
            print("  失败码:", dict(errs.most_common(8)))

    # regression: old success now fail
    regressed = [
        r
        for r in results
        if r["old_reason"] in {"success_silent", "ai_dry_run_success"} and r["replay"] == "FAIL"
    ]
    recovered = [
        r for r in results if r["old_reason"] == "ai_failed_replied" and r["replay"] == "PASS"
    ]
    print(f"\n原成功→现失败(回归): {len(regressed)}")
    print(f"原失败→现通过(修复): {len(recovered)}")
    if regressed[:10]:
        print("回归样例:")
        for r in regressed[:10]:
            print(f"  {r['ts']} chat={r['chat_id']} emp_tg={r['tg_id']} err={r['new_error']} sha={r['sha256']}")


async def main() -> None:
    print(f"拉取日志 month={MONTH_PREFIX} ...")
    lines = fetch_log_lines()
    samples = collect_samples(lines)
    print(f"去重有效打卡图: {len(samples)} concurrency={CONCURRENCY}")
    print(f"BBQ={sum(1 for s in samples if s['chat_id']==BBQ_CHAT)} "
          f"YYMG={sum(1 for s in samples if s['chat_id']==YYMG_CHAT)}")
    print("-" * 80)

    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    print(f"model={cfg.model}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        OUT_PATH.unlink()

    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict] = []
    t0 = time.perf_counter()
    done = 0

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
            p = sum(1 for x in results + [r] if x.get("replay") == "PASS")
            # results not yet appended here for concurrent - recount from file later
            print(f"[{done}/{len(samples)}] elapsed={elapsed/60:.1f}m eta={eta/60:.1f}m last={r['replay']} {r.get('new_error') or ''}")
        return r

    tasks = [asyncio.create_task(run_one(s)) for s in samples]
    results = await asyncio.gather(*tasks)
    _print_summary(list(results))
    print(f"\n明细已写入: {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
