#!/usr/bin/env python3
"""重跑 Y-UX-KQBBQ 北京时间当天打卡，并输出失败原因。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.getenv("ATTENDANCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

BBQ_CHAT_ID = -1003883297177
BJ = ZoneInfo("Asia/Shanghai")
# 默认：北京「今天」；可用 REPLAY_BJ_DATE=2026-07-11 覆盖
_bj_now = datetime.now(BJ)
_bj_day = os.getenv("REPLAY_BJ_DATE") or _bj_now.strftime("%Y-%m-%d")
_y, _m, _d = map(int, _bj_day.split("-"))
DAY_START_UTC = datetime(_y, _m, _d, 0, 0, 0, tzinfo=BJ).astimezone(timezone.utc).replace(tzinfo=None)
DAY_END_UTC = datetime(_y, _m, _d, 23, 59, 59, tzinfo=BJ).astimezone(timezone.utc).replace(tzinfo=None)

LOG_PATH = Path(os.getenv("REPLAY_LOG_PATH", ROOT / "logs" / "attendance-main.log"))
OUT_PATH = ROOT / "logs" / f"replay_bbq_bj_{_bj_day}.jsonl"

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


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    v = s.strip().strip("'")
    return None if v in ("None", "null", "") else v


def _parse_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def collect_samples(lines: list[str]) -> list[dict]:
    seen: set[str] = set()
    samples: list[dict] = []
    for i, line in enumerate(lines):
        m = PAT_ENTER.search(line)
        if not m:
            continue
        ts = _parse_ts(m.group(1))
        if not (DAY_START_UTC <= ts <= DAY_END_UTC):
            continue
        if int(m.group(3)) != BBQ_CHAT_ID:
            continue
        tg_id = int(m.group(2))
        ts_s = m.group(1)
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
        old_name = old_hint = old_time = old_date = emp = None
        for j in range(i + 1, min(i + 250, len(lines))):
            lj = lines[j]
            if "CHECKIN_RECOGNIZE" in lj and f"tg_id={tg_id}" in lj and (
                "stage=extracted" in lj or "stage=validate_failed" in lj or "stage=validated_ok" in lj
            ):
                if old_time is None:
                    old_name = _clean(re.search(r"ocr_name=([^ ]*)", lj).group(1))
                    old_hint = _clean(re.search(r"ocr_hint=([^ ]*)", lj).group(1))
                    old_time = _clean(re.search(r"ocr_time=([^ ]*)", lj).group(1))
                    old_date = _clean(re.search(r"ocr_date=([^ ]*)", lj).group(1))
                    em = re.search(r"employee_id=(\S+)", lj)
                    if em:
                        emp = em.group(1)
            mr = PAT_RETURN.search(lj)
            if mr and int(mr.group(2)) == tg_id:
                reason = mr.group(3)
                mc = PAT_CODE.search(lj)
                code = mc.group(1) if mc else None
                break
        if reason == "no_matter_in_caption_skip":
            continue
        seen.add(sha)
        bj = ts.replace(tzinfo=timezone.utc).astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S")
        samples.append(
            {
                "ts": ts_s,
                "bj_time": bj,
                "tg_id": tg_id,
                "file_id": fid,
                "sha256": sha[:16],
                "old_reason": reason,
                "old_code": code,
                "old_name": old_name,
                "old_hint": old_hint,
                "old_time": old_time,
                "old_date": old_date,
                "employee_id": emp,
            }
        )
    return samples


def explain_fail(r: dict) -> str:
    err = r.get("new_error") or ""
    name = r.get("new_name")
    clock = r.get("new_time")
    date = r.get("new_date")
    reg_u = r.get("reg_user")
    reg_n = r.get("reg_name")
    if err == "AI_USER_OTHER_PERSON":
        return f"AI 读到他人/非本人身份 {name!r}，登记为 {reg_u}/{reg_n}，判定代打或误读他人"
    if err == "AI_USER_MISMATCH":
        return f"AI 读到 {name!r}，与登记 {reg_u}/{reg_n} 对不上"
    if err == "AI_NAME_NOT_FOUND":
        return "图上未识别到有效姓名（可能只有群名噪声，已清空）"
    if err == "AI_NOT_GROUNDED":
        return f"姓名/字段无法在 AI 原文 grounding（name={name!r}）"
    if err == "AI_DATE_NOT_FOUND":
        return f"未识别到日期或日期无效（time={clock!r} date={date!r}）"
    if err == "AI_DATE_MISMATCH":
        return f"截图日期 {date!r} 与当天不一致"
    if err == "AI_TIME_SCREENSHOT_SKEW":
        return f"截图时间 {clock!r} 与发送时间差超过 30 分钟（旧图或读错钟）"
    if err == "AI_TIME_NOT_FOUND":
        return "未识别到有效打卡时间"
    if err == "AI_TIME_MISMATCH":
        return f"时间校验失败（time={clock!r}）"
    return f"错误码 {err}"


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
    date = ext.clock_date if ext else None
    base = {
        **sample,
        "employee_id": reg.employee_id,
        "reg_user": reg.tg_username,
        "reg_name": reg.english_name,
        "new_name": name,
        "new_time": clock,
        "new_date": date,
    }
    if ai_err is not None:
        return {**base, "replay": "FAIL", "new_error": ai_err.error_code}
    if ext is None:
        return {**base, "replay": "FAIL", "new_error": "AI_EXTRACT_FAILED"}
    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Shanghai",
        now_utc=ref_utc,
        max_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")),
        composite_screenshot=composite,
    )
    if hasattr(val, "ok") and not val.ok:
        return {**base, "replay": "FAIL", "new_error": val.error_code}
    return {**base, "replay": "PASS", "new_error": None}


async def main() -> None:
    print(f"BBQ 北京日={_bj_day} UTC窗口={DAY_START_UTC} ~ {DAY_END_UTC}")
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    useful = [
        l
        for l in lines
        if (
            "CHECKIN_HANDLER_ENTER]" in l
            or "image downloaded" in l
            or "CHECKIN_HANDLER_RETURN]" in l
            or "CHECKIN_RECOGNIZE" in l
        )
    ]
    samples = collect_samples(useful)
    print(f"样本数={len(samples)}")
    print("原结果:", Counter(s["old_reason"] for s in samples).most_common())
    if not samples:
        return

    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    print(f"model={cfg.model}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        OUT_PATH.unlink()

    results: list[dict] = []
    for i, sample in enumerate(samples, 1):
        r = await replay_one(sample, cfg=cfg)
        results.append(r)
        with OUT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        flag = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭"}[r["replay"]]
        print(
            f"[{i}/{len(samples)}] {flag} bj={r.get('bj_time')} emp={r.get('employee_id')} "
            f"old={r.get('old_reason')}/{r.get('old_code')} -> {r['replay']} "
            f"{r.get('new_error') or ''} name={r.get('new_name')!r} "
            f"time={r.get('new_time')!r} date={r.get('new_date')!r}",
            flush=True,
        )

    passed = sum(1 for r in results if r["replay"] == "PASS")
    failed = sum(1 for r in results if r["replay"] == "FAIL")
    skipped = sum(1 for r in results if r["replay"] == "SKIP")
    tested = passed + failed
    print("=" * 72)
    print(f"完成 {len(results)} | 可测 {tested} | 通过 {passed} | 失败 {failed} | 跳过 {skipped}")
    if tested:
        print(f"通过率: {passed}/{tested} = {100 * passed / tested:.1f}%")
    print("失败码:", dict(Counter(r["new_error"] for r in results if r["replay"] == "FAIL")))

    fails = [r for r in results if r["replay"] == "FAIL"]
    if fails:
        print("\n【失败明细与原因】")
        for r in fails:
            print("-" * 72)
            print(f"北京时间 {r.get('bj_time')} | 工号 {r.get('employee_id')} | sha={r['sha256']}")
            print(f"登记: {r.get('reg_user')} / {r.get('reg_name')}")
            print(
                f"当时线上: {r.get('old_reason')} {r.get('old_code') or ''} "
                f"识别={r.get('old_name')!r} 时间={r.get('old_time')!r} 日期={r.get('old_date')!r}"
            )
            print(
                f"本次重跑: {r.get('new_error')} "
                f"识别={r.get('new_name')!r} 时间={r.get('new_time')!r} 日期={r.get('new_date')!r}"
            )
            print(f"原因: {explain_fail(r)}")
    print(f"\n明细: {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
