# -*- coding: utf-8 -*-
"""自测 4 张图，结果写入 selftest_result.txt"""
from __future__ import annotations

import asyncio
import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "scripts" / "selftest_result.txt"

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from PIL import Image

from domain.shared.result import ServiceResult
from infra.checkin_ai_config import load_checkin_ai_config
from repositories.registrations_repo import get_by_tg_id
from services import checkin_extraction_validate_service
from services.checkin_image_ai_service import (
    _crop_checkin_regions,
    _isolate_timeis_canvas,
    _prepare_image_bytes,
    extract_checkin_from_image,
    pick_single_identity,
)
from services.checkin_name_verify_service import ocr_slack_name_from_panel

ASSETS = Path(r"C:\Users\test\.cursor\projects\d\assets")
CASES = [
    ("A群聊_考勤群错", "9f52e412"),
    ("B群聊_发Nayxua图", "36d0f56b"),
    ("C相册_benrenxing", "5feeb0e5"),
    ("D相册_Nayxua", "photo_2026"),
]


def log(msg: str) -> None:
    print(msg, flush=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def find(key: str) -> Path:
    for p in ASSETS.iterdir():
        if key in p.name and p.suffix.lower() == ".png":
            return p
    raise FileNotFoundError(key)


def name_regions(prep: bytes) -> dict[str, bytes]:
    iso = _isolate_timeis_canvas(prep)
    base = iso if iso is not prep else prep
    regions = _crop_checkin_regions(base)
    if iso is not prep:
        _, ih = Image.open(io.BytesIO(iso)).size
        if ih < 380:
            for k, v in _crop_checkin_regions(prep).items():
                if k.startswith("name_"):
                    regions[k] = v
    return regions


def ocr_quick(label: str, path: Path) -> None:
    prep = _prepare_image_bytes(path.read_bytes())
    w, h = Image.open(io.BytesIO(prep)).size
    reg = name_regions(prep)
    crop = reg.get("name_panel_bottom") or reg.get("name_panel") or prep
    ch, cw = Image.open(io.BytesIO(crop)).size
    t0 = time.perf_counter()
    read, ok = ocr_slack_name_from_panel(crop, extra_panels=[], expected_username="benrenxing")
    dt = time.perf_counter() - t0
    log(
        f"OCR {label}: img={w}x{h} crop={cw}x{ch} {dt:.1f}s "
        f"ok={ok} hint={read.username_hint!r} disp={read.display_name!r}"
    )


async def full_pipe(label: str, path: Path, cfg, reg) -> None:
    log(f"FULL {label} start...")
    t0 = time.perf_counter()
    ext, err = await extract_checkin_from_image(
        image_bytes=path.read_bytes(),
        config=cfg,
        expected_tg_username="benrenxing",
        shift_timezone="Asia/Bangkok",
    )
    dt = time.perf_counter() - t0
    if err:
        log(f"FULL {label}: FAIL [{err.error_code}] {err.message.split(chr(10))[0]} ({dt:.0f}s)")
        return
    ident = pick_single_identity(ext)
    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Bangkok",
        now_utc=datetime.now(timezone.utc),
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=cfg.trust_sender_when_name_unreadable,
    )
    if isinstance(val, ServiceResult):
        log(
            f"FULL {label}: extract OK ident={ident!r} clock={ext.clock_time!r} "
            f"validate FAIL [{val.error_code}] {val.message.split(chr(10))[0]} ({dt:.0f}s)"
        )
    else:
        log(
            f"FULL {label}: extract OK ident={ident!r} clock={ext.clock_time!r} "
            f"validate PASS ({dt:.0f}s)"
        )


async def main() -> None:
    OUT.write_text("", encoding="utf-8")
    cfg = load_checkin_ai_config()
    reg = get_by_tg_id(1302377984)
    log(f"config name_verify={cfg.name_verify_mode} trust_sender={cfg.trust_sender_when_name_unreadable}")
    log(f"account={reg.tg_username if reg else None}")
    log("--- OCR (单块 name_panel_bottom) ---")
    for label, key in CASES:
        ocr_quick(label, find(key))
    if not reg:
        log("SKIP full: no registration")
        return
    log("--- FULL pipeline ---")
    for label, key in CASES:
        await full_pipe(label, find(key), cfg, reg)
    log("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
