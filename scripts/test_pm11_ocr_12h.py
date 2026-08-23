#!/usr/bin/env python3
"""Regression: Google「北京时间」页 下午11:26 → OCR 应通过 ±12h 选到 23:26。"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("ATTENDANCE_ROOT", "/app"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.checkin_extraction_validate_service import validate_extraction_for_checkin
from services.checkin_image_ai_service import (
    _clock_candidates_from_text,
    _crop_checkin_regions,
    _flip_12h_clock_candidate,
    _minutes_from_reference,
    _pick_clock_by_inclusion,
    _prepare_image_bytes,
    ocr_clock_from_regions,
)
from services.checkin_ocrspace_service import extract_checkin_from_ocrspace

IMG_PATH = Path(os.environ.get("TEST_IMAGE", "/tmp/pm11_beijing_time.png"))


def test_flip_unit() -> None:
    assert _flip_12h_clock_candidate("11:26:00") == "23:26:00"
    assert _flip_12h_clock_candidate("23:26:00") == "11:26:00"
    print("unit_flip PASS")


def test_inclusion_from_text() -> None:
    ocr_snippet = "北京时间\n下午11:26\n2026年8月23日"
    cands = {c: hs for c, hs in _clock_candidates_from_text(ocr_snippet)}
    ref = datetime(2026, 8, 23, 15, 26, 30, tzinfo=timezone.utc)  # 23:26 北京
    pick, rejected = _pick_clock_by_inclusion(
        cands,
        reference_utc=ref,
        tz_name="Asia/Shanghai",
        max_skew_minutes=60,
    )
    assert pick == "23:26:00", f"expected 23:26:00 got {pick!r} cands={cands} rejected={rejected}"
    skew = _minutes_from_reference(clock_str=pick, reference_utc=ref, tz_name="Asia/Shanghai")
    assert skew <= 1.0, f"skew too large {skew}"
    print(f"inclusion_from_text PASS pick={pick} skew={skew:.2f}m")


async def test_ocrspace_image() -> None:
    if not IMG_PATH.is_file():
        print(f"skip ocrspace_image: no file {IMG_PATH}")
        return
    img = IMG_PATH.read_bytes()
    cfg = SimpleNamespace(max_clock_skew_minutes=int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES", "30")))
    ref = datetime(2026, 8, 23, 15, 26, 39, tzinfo=timezone.utc)
    reg = SimpleNamespace(
        english_name="Karina",
        employee_id="4257",
        telegram_user_id=7056750099,
        telegram_username="Y_UX_Karina",
    )
    ext, err = await extract_checkin_from_ocrspace(
        image_bytes=img,
        config=cfg,
        expected_tg_username="Y_UX_Karina",
        expected_english_name="Karina",
        reference_utc=ref,
        shift_timezone="Asia/Shanghai",
    )
    local = ref.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"ref_local={local} backend=ocrspace")
    if err is not None:
        print(f"RESULT FAIL_EXTRACT {err.error_code} {err.message}")
        raise SystemExit(1)
    print(
        f"clock={ext.clock_time} date={ext.clock_date} "
        f"skew_rejected={ext.clock_skew_rejected} name={ext.display_name or ext.username_hint}"
    )
    if not ext.clock_time:
        print("RESULT FAIL_NO_CLOCK")
        raise SystemExit(1)
    skew = _minutes_from_reference(
        clock_str=ext.clock_time, reference_utc=ref, tz_name="Asia/Shanghai"
    )
    print(f"skew_min={skew:.2f}")
    out = validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Shanghai",
        now_utc=ref,
        max_skew_minutes=cfg.max_clock_skew_minutes,
        skip_identity_verify=True,
    )
    if ext.clock_time.startswith("23:26") and skew <= cfg.max_clock_skew_minutes + 0.5:
        print("RESULT PASS (±12h → 23:26)")
    elif isinstance(out, datetime):
        print(f"RESULT PASS validate={out.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()}")
    else:
        code = getattr(out, "error_code", None) or getattr(out, "code", None)
        print(f"RESULT FAIL validate={code} clock={ext.clock_time}")
        raise SystemExit(1)


def test_local_ocr_regions() -> None:
    if not IMG_PATH.is_file():
        print(f"skip local_ocr_regions: no file {IMG_PATH}")
        return
    img = IMG_PATH.read_bytes()
    ref = datetime(2026, 8, 23, 15, 26, 39, tzinfo=timezone.utc)
    prepared = _prepare_image_bytes(img)
    regions = _crop_checkin_regions(prepared)
    pick, skew_rejected = ocr_clock_from_regions(
        regions,
        reference_utc=ref,
        tz_name="Asia/Shanghai",
        max_skew_minutes=30,
        prepared_bytes=prepared,
        fast=True,
    )
    print(
        f"local_ocr pick={pick!r} skew_rejected={skew_rejected} "
        f"ref_local={ref.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%H:%M:%S')}"
    )
    if not pick:
        print("RESULT FAIL local_ocr NO_CLOCK")
        raise SystemExit(1)
    skew = _minutes_from_reference(clock_str=pick, reference_utc=ref, tz_name="Asia/Shanghai")
    print(f"local_ocr skew_min={skew:.2f}")
    if pick.startswith("23:26") and skew <= 30.5 and not skew_rejected:
        print("RESULT PASS local_ocr (±12h → 23:26)")
    else:
        print(f"RESULT FAIL local_ocr clock={pick} skew={skew:.2f}")
        raise SystemExit(1)


async def main() -> None:
    test_flip_unit()
    test_inclusion_from_text()
    test_local_ocr_regions()
    await test_ocrspace_image()


if __name__ == "__main__":
    asyncio.run(main())
