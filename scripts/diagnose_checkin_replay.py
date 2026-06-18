# -*- coding: utf-8 -*-
"""复现打卡识别并逐步对比：下载图 → 裁切 → OCR → 完整 extract → validate。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

# 用户 2026-05-19 群打卡失败同一张图（日志 file_id / raw sha256 前缀）
DEFAULT_FILE_ID = (
    "AgACAgUAAyEFAAS-vNSdAAIBymoMxU5FUolFMx_WomTzBYFGW7ilAAIxEmsb_gFoVDH8GI9oGGWMAQADAgADeQADOwQ"
)
EXPECTED_USER = "benrenxing"
EXPECTED_CLOCK = "20:31:04"
TG_ID = 1302377984


async def _download_telegram(file_id: str) -> bytes:
    import httpx
    import os

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未配置")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        path = r.json()["result"]["file_path"]
        r2 = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
        r2.raise_for_status()
        return r2.content


def _sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file-id", default=DEFAULT_FILE_ID)
    parser.add_argument("--image", type=Path, help="本地图片（优先于 Telegram 下载）")
    parser.add_argument("--ref-utc", default="2026-05-19T12:26:00+00:00")
    args = parser.parse_args()

    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id
    from services import checkin_extraction_validate_service
    from services.checkin_image_ai_service import (
        _crop_checkin_regions,
        _image_digest,
        _prepare_image_bytes,
        extract_checkin_from_image,
        ocr_clock_from_regions,
    )
    from services.checkin_name_verify_service import (
        ocr_hunt_regions_parallel,
        ocr_slack_name_from_panel,
        ocr_thorough_best_panel,
    )

    if args.image and args.image.is_file():
        raw = args.image.read_bytes()
        src = f"local:{args.image}"
    else:
        print("从 Telegram 下载…")
        raw = await _download_telegram(args.file_id)
        src = f"telegram:{args.file_id[:24]}…"
        cache = ROOT / "scripts" / "_replay_cache_user_flat.jpg"
        cache.write_bytes(raw)
        print(f"已缓存到 {cache}")

    prep = _prepare_image_bytes(raw)
    ref = datetime.fromisoformat(args.ref_utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    cfg = load_checkin_ai_config()
    reg = get_by_tg_id(TG_ID)

    from PIL import Image

    img = Image.open(io.BytesIO(prep))
    w, h = img.size

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("打卡识别复现对比")
    lines.append("=" * 60)
    lines.append(f"来源: {src}")
    lines.append(f"raw_sha256={_sha16(raw)}  prepared_sha256={_image_digest(prep)[:16]}")
    lines.append(f"尺寸: {w}x{h}  bytes={len(raw)}")
    lines.append(
        f"配置: backend={cfg.extract_backend} name_verify={cfg.name_verify_mode} "
        f"clock_fallback={cfg.clock_fallback_send_time} skew_max={cfg.max_clock_skew_minutes}m"
    )
    lines.append(f"登记用户: tg={TG_ID} username={reg.tg_username if reg else '?'}")
    lines.append(f"期望: user={EXPECTED_USER} clock≈{EXPECTED_CLOCK}")
    lines.append("")

  # 逐步 OCR
    regions = _crop_checkin_regions(prep)
    lines.append("--- 裁切区 ---")
    for k in sorted(regions.keys()):
        lines.append(f"  {k}: {len(regions[k]) // 1024}KB")
    lines.append("")

    tz = "Asia/Bangkok"
    lines.append("--- 姓名 OCR 分步 ---")
    for key in (
        "name_panel_overlay",
        "name_panel_bottom",
        "name_panel_row",
        "name_panel_tight",
        "name_panel",
    ):
        chunk = regions.get(key)
        if not chunk:
            lines.append(f"  [{key}] (无裁切)")
            continue
        read, avail = ocr_slack_name_from_panel(
            chunk, expected_username=EXPECTED_USER, fast=True
        )
        raw_snip = ((read.raw_text or "")[:80]) if read else ""
        lines.append(
            f"  [{key}] avail={avail} hint={read.username_hint!r} raw={raw_snip!r}"
        )

    hunt = ocr_hunt_regions_parallel(regions, EXPECTED_USER)
    lines.append(
        f"  [hunt_parallel] hint={hunt.username_hint if hunt else None!r} "
        f"raw={(hunt.raw_text[:80] if hunt and hunt.raw_text else '')!r}"
    )
    thorough = ocr_thorough_best_panel(
        regions, EXPECTED_USER, keys=("name_panel_bottom", "name_panel_overlay")
    )
    lines.append(
        f"  [thorough] hint={thorough.username_hint if thorough else None!r}"
    )
    lines.append("")

    lines.append("--- 时间 OCR 分步 ---")
    from services.checkin_image_ai_service import _ocr_clock_from_crop_bytes, _clock_skew_minutes

    for key in ("time_main", "time_digits", "time_clock", "time_panel", "time_top"):
        chunk = regions.get(key)
        if not chunk:
            continue
        t = _ocr_clock_from_crop_bytes(chunk, reference_utc=ref, tz_name=tz)
        skew = _clock_skew_minutes(t, reference_utc=ref, tz_name=tz) if t else None
        ok = skew is not None and skew <= cfg.max_clock_skew_minutes
        lines.append(f"  [{key}] clock={t!r} skew_min={skew} accept={ok}")

    merged = ocr_clock_from_regions(
        regions,
        reference_utc=ref,
        tz_name=tz,
        prepared_bytes=prep,
        max_skew_minutes=cfg.max_clock_skew_minutes,
    )
    lines.append(f"  [ocr_clock_from_regions] => {merged!r}")
    lines.append("")

    lines.append("--- 完整 extract_checkin_from_image ---")
    t0 = time.perf_counter()
    ext, err = await extract_checkin_from_image(
        image_bytes=raw,
        config=cfg,
        expected_tg_username=EXPECTED_USER,
        expected_english_name=reg.english_name if reg else None,
        reference_utc=ref,
        shift_timezone=tz,
    )
    dt = time.perf_counter() - t0
    if err:
        lines.append(f"  FAIL [{err.error_code}] ({dt:.1f}s)")
        lines.append(f"  msg: {err.message.splitlines()[0]}")
    else:
        lines.append(
            f"  OK ({dt:.1f}s) user={ext.username_hint!r} clock={ext.clock_time!r} "
            f"date={ext.clock_date!r}"
        )

    if ext and reg and not err:
        lines.append("")
        lines.append("--- validate_extraction_for_checkin ---")
        val = checkin_extraction_validate_service.validate_extraction_for_checkin(
            extraction=ext,
            reg=reg,
            shift_timezone=tz,
            now_utc=ref,
            max_skew_minutes=cfg.max_clock_skew_minutes,
        )
        if hasattr(val, "ok"):
            lines.append(f"  validate FAIL [{val.error_code}] {val.message}")
        else:
            lines.append(f"  validate OK clock_utc={val}")

    lines.append("")
    lines.append("--- 与期望对比 ---")
    got_user = ext.username_hint if ext else None
    got_clock = ext.clock_time if ext else None
    user_ok = got_user == EXPECTED_USER
    clock_ok = got_clock == EXPECTED_CLOCK
    lines.append(f"  姓名: 期望={EXPECTED_USER} 实际={got_user!r}  {'OK' if user_ok else 'MISMATCH'}")
    lines.append(f"  时间: 期望={EXPECTED_CLOCK} 实际={got_clock!r}  {'OK' if clock_ok else 'MISMATCH'}")
    if err:
        lines.append(f"  错误码: {err.error_code}（用户看到: 姓名/时间不一致类文案）")

    report = "\n".join(lines)
    out = ROOT / "scripts" / "diagnose_checkin_replay_result.txt"
    out.write_text(report, encoding="utf-8")
    sys.stdout.buffer.write(report.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")
    print(f"(written {out})")
    return 0 if user_ok and clock_ok and not err else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
