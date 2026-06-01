"""快速自测：裁切 + OCR（不调 ollama）；可选单张完整 extract。"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from PIL import Image

from services.checkin_image_ai_service import (  # noqa: E402
    _crop_checkin_regions,
    _isolate_timeis_canvas,
    _prepare_image_bytes,
    is_slack_panel_likely_cropped_off,
)
from services.checkin_name_verify_service import ocr_slack_name_from_panel  # noqa: E402

ASSETS = Path(r"C:\Users\test\.cursor\projects\d\assets")
TESTS = [
    ("图A_群聊_考勤群错误", "image-9f52e412-a183-4098-8bf1-2b7aa8cc5ad4.png"),
    ("图B_群聊_benrenxing发Nayxua", "image-36d0f56b-9c93-498a-9396-b0bedcb4b2d3.png"),
    ("图C_相册_benrenxing", "image-5feeb0e5-37bd-416b-ba40-76b5a6a87dd7.png"),
    ("图D_相册_Nayxua", "photo_2026-05-15_18-39-38-00b4c304-7131-459a-9f09-9bd42998bedd.png"),
]


def resolve_path(suffix: str) -> Path | None:
    for p in ASSETS.glob(f"*{suffix}"):
        return p
    return None


def ocr_phase(label: str, path: Path) -> None:
    raw = path.read_bytes()
    prep = _prepare_image_bytes(raw)
    iso = _isolate_timeis_canvas(prep)
    name_src = prep if (iso is prep or Image.open(io.BytesIO(iso)).size[1] >= 380) else prep
    if iso is not prep:
        _, ih = Image.open(io.BytesIO(iso)).size
        if ih < 380 or is_slack_panel_likely_cropped_off(iso):
            name_src = prep
    w, h = Image.open(io.BytesIO(prep)).size
    print(f"\n--- {label} --- prep={w}x{h}")
    regions = _crop_checkin_regions(iso if iso is not prep else prep)
    if name_src is not prep and name_src is not iso:
        for k, v in _crop_checkin_regions(name_src).items():
            if k.startswith("name_"):
                regions[k] = v
    crops = [
        regions[k]
        for k in (
            "name_panel_bottom",
            "name_panel_row",
            "name_panel_tight",
            "name_panel",
            "name_panel_alt",
        )
        if k in regions
    ]
    for k in sorted(regions):
        if k.startswith("name_"):
            im = Image.open(io.BytesIO(regions[k]))
            print(f"  {k}: {im.size[0]}x{im.size[1]}")
    read, ok = ocr_slack_name_from_panel(
        crops[0] if crops else prep,
        extra_panels=crops[1:],
        expected_username="benrenxing",
    )
    print(f"  OCR: ok={ok} hint={read.username_hint!r} display={read.display_name!r}")


async def full_one(label: str, path: Path) -> None:
    from datetime import datetime, timezone

    from domain.shared.result import ServiceResult
    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id
    from services import checkin_extraction_validate_service
    from services.checkin_image_ai_service import extract_checkin_from_image, pick_single_identity

    print(f"\n=== 完整流水线 {label} ===")
    cfg = load_checkin_ai_config()
    ext, err = await extract_checkin_from_image(
        image_bytes=path.read_bytes(),
        config=cfg,
        expected_tg_username="benrenxing",
        shift_timezone="Asia/Bangkok",
    )
    if err:
        print(f"  FAIL [{err.error_code}] {err.message[:120]}")
        return
    print(f"  OK clock={ext.clock_time!r} identity={pick_single_identity(ext)!r}")
    reg = get_by_tg_id(1302377984)
    if not reg or not ext:
        return
    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Bangkok",
        now_utc=datetime.now(timezone.utc),
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=cfg.trust_sender_when_name_unreadable,
    )
    if isinstance(val, ServiceResult):
        print(f"  validate FAIL [{val.error_code}] {val.message.split(chr(10))[0]}")
    else:
        print(f"  validate PASS")


async def main() -> None:
    print("【1】OCR 快速（约 1 分钟内）")
    for label, suf in TESTS:
        p = resolve_path(suf)
        if p:
            ocr_phase(label, p)
        else:
            print(f"\n--- {label} --- 文件缺失")

    print("\n【2】完整 AI：仅相册图 C、D（各约 1~2 分钟）")
    for label, suf in TESTS[2:]:
        p = resolve_path(suf)
        if p:
            await full_one(label, p)


if __name__ == "__main__":
    asyncio.run(main())
