# -*- coding: utf-8 -*-
"""从工号打卡群日志提取历史截图，批量重跑 remote_diff 识别并统计成功率。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

_PAT_DL = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*image downloaded file_id=(\S+) sha256=([a-f0-9]+)"
)
_PAT_REMOTE = re.compile(
    r"remote_diff mode chat_id=-5474909614 title='工号打卡群' tg_id=(\d+)"
)
_PAT_FAIL = re.compile(r"error=(REMOTE_[A-Z_]+|AI_[A-Z_]+)")


def _parse_log_samples(log_path: Path) -> list[dict]:
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    by_sha: OrderedDict[str, dict] = OrderedDict()

    for i, line in enumerate(lines):
        m_remote = _PAT_REMOTE.search(line)
        if not m_remote:
            continue
        tg_id = int(m_remote.group(1))
        dl = None
        for j in range(max(0, i - 3), i):
            m_dl = _PAT_DL.search(lines[j])
            if m_dl:
                dl = m_dl
                break
        if not dl:
            continue

        ts_s, file_id, sha = dl.group(1), dl.group(2), dl.group(3)
        log_err: str | None = None
        log_ok = False
        for k in range(i, min(len(lines), i + 60)):
            if "remote_validated_ok" in lines[k]:
                log_ok = True
                break
            if "persist_clock_record" in lines[k] and "remote" in lines[k]:
                log_ok = True
                break
            if "handler_rejected" in lines[k] or "remote_validate_failed" in lines[k]:
                m_fail = _PAT_FAIL.search(lines[k])
                if m_fail:
                    log_err = m_fail.group(1)
                    break

        key = sha
        if key not in by_sha:
            by_sha[key] = {
                "sha256": sha,
                "file_id": file_id,
                "tg_id": tg_id,
                "sent_at": ts_s,
                "log_ok": log_ok,
                "log_error": log_err,
            }

    return list(by_sha.values())


async def _download_telegram(file_id: str) -> bytes | None:
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未配置")
    async with httpx.AsyncClient(timeout=90) as client:
        try:
            r = await client.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": file_id},
            )
            r.raise_for_status()
            path = r.json()["result"]["file_path"]
            r2 = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
            r2.raise_for_status()
            return r2.content
        except Exception:
            return None


def _sent_utc(sent_at: str) -> datetime:
    local = datetime.strptime(sent_at, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=ZoneInfo("Asia/Shanghai")
    )
    return local.astimezone(timezone.utc)


async def _replay_one(sample: dict, *, shift_timezone: str, recognition_only: bool) -> dict:
    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id

    cfg = load_checkin_ai_config()
    image_bytes = await _download_telegram(sample["file_id"])
    if not image_bytes:
        return {
            **sample,
            "ok": False,
            "recognition_ok": False,
            "error_code": "DOWNLOAD_FAILED",
            "message": "图片下载失败",
            "match_log": False,
            "sec": 0.0,
        }

    import time

    t0 = time.perf_counter()

    if recognition_only:
        from services.checkin_remote_diff_service import extract_remote_checkin_from_zhipu

        reg = get_by_tg_id(int(sample["tg_id"]))
        expected_id = str(reg.employee_id) if reg else ""
        remote, ai_err = await extract_remote_checkin_from_zhipu(
            image_bytes=image_bytes,
            config=cfg,
            tg_id=int(sample["tg_id"]),
            reference_utc=_sent_utc(sample["sent_at"]),
            shift_timezone=shift_timezone,
        )
        sec = round(time.perf_counter() - t0, 1)
        if ai_err is not None:
            return {
                **sample,
                "ok": False,
                "recognition_ok": False,
                "error_code": ai_err.error_code,
                "message": ai_err.message,
                "desktop_id": None,
                "folder": None,
                "match_log": False,
                "sec": sec,
            }
        if remote is None:
            return {
                **sample,
                "ok": False,
                "recognition_ok": False,
                "error_code": "AI_EXTRACT_FAILED",
                "message": "extract failed",
                "desktop_id": None,
                "folder": None,
                "match_log": False,
                "sec": sec,
            }

        desktop_id = remote.desktop_employee_id
        folder = remote.has_green_person_folder
        beijing = remote.has_beijing_time
        rec_err: str | None = None
        if not beijing or not remote.extraction.clock_time:
            rec_err = "AI_TIME_NOT_FOUND"
        elif not desktop_id or not folder:
            rec_err = "REMOTE_EMPLOYEE_ID_NOT_FOUND"
        elif desktop_id != expected_id:
            rec_err = "REMOTE_EMPLOYEE_ID_MISMATCH"

        recognition_ok = rec_err is None
        return {
            **sample,
            "ok": recognition_ok,
            "recognition_ok": recognition_ok,
            "error_code": rec_err,
            "message": "recognition_ok" if recognition_ok else rec_err,
            "desktop_id": desktop_id,
            "folder": folder,
            "clock_time": remote.extraction.clock_time,
            "match_log": _match_log(sample, recognition_ok, rec_err),
            "sec": sec,
        }

    from services.checkin_ai_orchestrator import resolve_clock_time_with_ai_from_bytes

    result = await resolve_clock_time_with_ai_from_bytes(
        image_bytes=image_bytes,
        tg_id=int(sample["tg_id"]),
        shift_timezone=shift_timezone,
        config=cfg,
        message_sent_utc=_sent_utc(sample["sent_at"]),
        chat_id=-5474909614,
        chat_title="工号打卡群",
    )
    sec = round(time.perf_counter() - t0, 1)

    if hasattr(result, "ok"):
        ok = bool(result.ok)
        err = getattr(result, "error_code", None)
        msg = getattr(result, "message", None)
    else:
        ok = True
        err = None
        msg = "success"

    return {
        **sample,
        "ok": ok,
        "recognition_ok": ok,
        "error_code": err,
        "message": msg,
        "match_log": _match_log(sample, ok, err),
        "sec": sec,
    }


def _match_log(sample: dict, ok: bool, err: str | None) -> bool | None:
    log_err = sample.get("log_error")
    log_ok = sample.get("log_ok")
    if log_ok:
        return ok
    if log_err:
        return (not ok) and (err == log_err)
    return None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "logs" / "attendance-main.log",
        help="attendance-main.log 路径",
    )
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "scripts" / "batch_remote_diff_replay_result.json",
    )
    parser.add_argument("--limit", type=int, default=0, help="只测前 N 张，0=全部")
    parser.add_argument("--tg-id", type=int, default=0, help="只测指定 tg_id，0=全部")
    parser.add_argument(
        "--recognition-only",
        action="store_true",
        help="只统计工号+图标+北京时间识别，不做截图时间偏差校验",
    )
    args = parser.parse_args()

    if not args.log.is_file():
        print(f"log not found: {args.log}")
        return 1

    samples = _parse_log_samples(args.log)
    if args.tg_id:
        samples = [s for s in samples if s["tg_id"] == args.tg_id]
    if args.limit > 0:
        samples = samples[: args.limit]

    if not samples:
        print("no samples")
        return 1

    print(f"replaying {len(samples)} unique images from 工号打卡群 ...", flush=True)
    results: list[dict] = []
    for idx, sample in enumerate(samples, start=1):
        sha8 = sample["sha256"][:8]
        print(
            f"[{idx}/{len(samples)}] sha={sha8} tg={sample['tg_id']} "
            f"log={'OK' if sample['log_ok'] else sample.get('log_error', '?')}",
            flush=True,
        )
        item = await _replay_one(
            sample, shift_timezone=args.timezone, recognition_only=args.recognition_only
        )
        results.append(item)
        status = "OK" if item["ok"] else f"FAIL {item.get('error_code')}"
        ml = item.get("match_log")
        ml_s = "match" if ml else ("diff" if ml is False else "n/a")
        print(f"  -> {status} {item['sec']}s log_{ml_s}", flush=True)
        await asyncio.sleep(0.3)

        if idx % 5 == 0:
            partial = {
                "progress": f"{idx}/{len(samples)}",
                "success_so_far": sum(1 for r in results if r.get("ok")),
                "results": results,
            }
            args.out.with_suffix(".partial.json").write_text(
                json.dumps(partial, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    ok_count = sum(1 for r in results if r.get("ok"))
    match_count = sum(1 for r in results if r.get("match_log") is True)
    known_log = [r for r in results if r.get("log_ok") or r.get("log_error")]
    summary = {
        "group": "工号打卡群",
        "chat_id": -5474909614,
        "mode": "recognition_only" if args.recognition_only else "full_pipeline",
        "total": len(results),
        "success": ok_count,
        "failed": len(results) - ok_count,
        "success_rate_pct": round(ok_count / len(results) * 100, 1) if results else 0.0,
        "same_as_log": match_count,
        "same_as_log_rate_pct": round(match_count / len(known_log) * 100, 1) if known_log else 0.0,
        "avg_sec": round(sum(r.get("sec", 0) for r in results) / len(results), 1),
        "results": results,
    }
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("---")
    print(f"total={summary['total']} success={summary['success']} failed={summary['failed']}")
    print(f"success_rate={summary['success_rate_pct']}%")
    print(f"same_as_log={summary['same_as_log']}/{len(known_log)} ({summary['same_as_log_rate_pct']}%)")
    print(f"avg_sec={summary['avg_sec']}")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
