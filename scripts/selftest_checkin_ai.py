"""打卡 AI 自测：Ollama 连通、截图提取、校验逻辑。"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from domain.shared.result import ServiceResult  # noqa: E402
from infra.checkin_ai_config import load_checkin_ai_config  # noqa: E402
from repositories.registrations_repo import get_by_tg_id  # noqa: E402
from services import checkin_extraction_validate_service  # noqa: E402
from services.checkin_image_ai_service import extract_checkin_from_image  # noqa: E402

BENREN_TG_ID = 1302377984
ASSET_GLOBS = (
    "c__Users_test_AppData_Roaming_Cursor_User_workspaceStorage_*_images_image-*.png",
)


def find_test_images() -> list[Path]:
    bases = [
        Path(r"C:\Users\test\.cursor\projects\d\assets"),
        ROOT.parent,
    ]
    explicit = [
        Path(
            r"C:\Users\test\.cursor\projects\d\assets"
            r"\c__Users_test_AppData_Roaming_Cursor_User_workspaceStorage_"
            r"22ebd0a5343d9ee451e3cbfc25a6e09d_images_image-5feeb0e5-37bd-416b-ba40-76b5a6a87dd7.png"
        ),
        Path(
            r"C:\Users\test\.cursor\projects\d\assets"
            r"\c__Users_test_AppData_Roaming_Cursor_User_workspaceStorage_"
            r"22ebd0a5343d9ee451e3cbfc25a6e09d_images_image-7b26f026-c34c-4f69-8925-6f1ebc308f67.png"
        ),
    ]
    for p in explicit:
        if p.is_file():
            bases.insert(0, p.parent)
    found: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.png")):
            if "image-" in p.name and p.stat().st_size > 10_000:
                found.append(p)
    # 去重
    seen: set[str] = set()
    out: list[Path] = []
    for p in found:
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out[:5]


async def test_ollama_ping() -> tuple[bool, str]:
    import httpx

    cfg = load_checkin_ai_config()
    root = cfg.base_url.replace("/v1", "").rstrip("/")
    if "11434" not in root:
        root = "http://127.0.0.1:11434"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{root}/api/tags")
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", []) if isinstance(m, dict)]
        has_model = any(cfg.model in n or n.startswith(cfg.model) for n in names)
        return has_model, f"models={len(names)} has_{cfg.model}={has_model}"
    except Exception as exc:
        return False, str(exc)


async def test_extract(img: Path, expected_user: str | None) -> dict:
    cfg = load_checkin_ai_config()
    ext, err = await extract_checkin_from_image(
        image_bytes=img.read_bytes(),
        config=cfg,
        expected_tg_username=expected_user,
    )
    return {
        "file": img.name,
        "error": None if err is None else f"{err.error_code}: {err.message[:80]}",
        "clock": ext.clock_time if ext else None,
        "display": ext.display_name if ext else None,
        "hint": ext.username_hint if ext else None,
    }


def test_validate(reg_tg_id: int, extraction_clock: str, extraction_name: str | None, extraction_hint: str | None):
    from domain.checkin_image_extraction import CheckinImageExtraction

    reg = get_by_tg_id(reg_tg_id)
    if not reg:
        return {"validate": "SKIP", "reason": "no registration"}
    cfg = load_checkin_ai_config()
    ext = CheckinImageExtraction(
        display_name=extraction_name,
        username_hint=extraction_hint,
        clock_time=extraction_clock,
        clock_date=None,
        timezone_iana="Asia/Shanghai",
        confidence=None,
    )
    result = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Bangkok",
        now_utc=datetime.now(timezone.utc),
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=cfg.trust_sender_when_name_unreadable,
    )
    if isinstance(result, ServiceResult):
        return {"validate": "FAIL", "code": result.error_code, "msg": result.message.split("\n")[0]}
    return {"validate": "OK", "clock_utc": result.isoformat()}


async def main() -> int:
    print("=== 打卡 AI 自测 ===\n")
    cfg = load_checkin_ai_config()
    print(f"config: enabled={cfg.enabled} model={cfg.model} trust_sender={cfg.trust_sender_when_name_unreadable}")

    ok, ping_msg = await test_ollama_ping()
    print(f"\n[1] Ollama: {'PASS' if ok else 'FAIL'} — {ping_msg}")
    if not ok:
        return 1

    reg = get_by_tg_id(BENREN_TG_ID)
    print(f"\n[2] DB 用户 benrenxing: {'PASS' if reg else 'FAIL'}")
    if reg:
        print(f"    tg_username={reg.tg_username} employee_id={reg.employee_id} shift_id={reg.shift_id}")

    images = find_test_images()
    print(f"\n[3] 找到测试图: {len(images)} 张")
    if not images:
        print("    SKIP 图像提取（无本地测试 PNG）")
    else:
        for img in images:
            row = await test_extract(img, reg.tg_username if reg else None)
            status = "PASS" if row["error"] is None else "FAIL"
            print(f"\n    [{status}] {row['file']}")
            print(f"         clock={row['clock']} display={row['display']} hint={row['hint']}")
            if row["error"]:
                print(f"         err={row['error']}")
            elif reg and row["clock"]:
                v = test_validate(
                    BENREN_TG_ID,
                    row["clock"],
                    row["display"],
                    row["hint"],
                )
                print(f"         validate={v}")

    # 合成用例：模拟读出他人姓名
    print("\n[4] 校验逻辑（合成数据，不调用视觉模型）")
    if reg:
        cases = [
            ("benrenxing 本人 + 当前时间格式", "20:12:00", "benrenxing Z", "benrenxing"),
            ("他人 Nayxua", "13:53:08", "Y_UX_Nayxua 朵拉", "Y_UX_Nayxua"),
            ("无姓名（应拒绝）", "20:12:00", None, None),
        ]
        for label, clk, disp, hint in cases:
            v = test_validate(BENREN_TG_ID, clk, disp, hint)
            print(f"    {label}: {v.get('validate')} {v.get('code') or v.get('clock_utc', '')}")

    print("\n=== 自测结束 ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
