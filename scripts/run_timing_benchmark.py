# -*- coding: utf-8 -*-
"""打卡 AI 耗时自测（需 Ollama 已启动）。

用法:
  python scripts/run_timing_benchmark.py
  python scripts/checkin_ai_selftest.py --fast   # 无 Ollama 时仅跑单元回归
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")


def _ollama_candidates() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        Path(local) / "Programs" / "Ollama" / "ollama.exe",
        Path(r"C:\Program Files\Ollama\ollama.exe"),
    ]


def _print_ollama_help(root: str, exc: Exception) -> None:
    print(f"FAIL: Ollama 未运行 ({root}): {exc}")
    found = [p for p in _ollama_candidates() if p.is_file()]
    if found:
        print("\n本机已安装 Ollama，请先启动：")
        print("  - 开始菜单打开「Ollama」托盘应用，或")
        print(f"  - 在终端执行: \"{found[0]}\" serve")
    else:
        print("\n未检测到 Ollama 安装。请：")
        print("  1. 从 https://ollama.com/download 安装 Windows 版")
        print("  2. 安装后打开 Ollama，等待托盘图标就绪")
        print("  3. 拉取模型: ollama pull moondream")
    print("\n验证服务: 浏览器打开 http://127.0.0.1:11434/api/tags 应返回 JSON")
    print("无需测耗时时可先跑: python scripts/checkin_ai_selftest.py --fast")


async def main() -> int:
    import httpx
    from PIL import Image

    from infra.checkin_ai_config import load_checkin_ai_config
    from services.checkin_image_ai_service import extract_checkin_from_image

    cfg = load_checkin_ai_config()
    root = cfg.base_url.replace("/v1", "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(f"{root}/api/tags")
    except Exception as exc:
        _print_ollama_help(root, exc)
        return 1

    assets = Path(
        __import__("os").getenv(
            "CHECKIN_SELFTEST_ASSETS",
            r"C:\Users\test\.cursor\projects\d\assets",
        )
    )
    cases: list[tuple[str, bytes]] = []
    e = next(assets.glob("*215f78a8*"), None)
    d = next(assets.glob("*photo_2026*"), None)
    if e:
        cases.append(("E_本人原图", e.read_bytes()))
        img = Image.open(e).convert("RGB").resize((1280, 463), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        cases.append(("F_扁图模拟", buf.getvalue()))
    if d:
        cases.append(("D_他人Nayxua", d.read_bytes()))

    print(f"model={cfg.model} 目标: 单次 <= 25s\n")
    failed = 0
    for label, data in cases:
        t0 = time.perf_counter()
        ext, err = await extract_checkin_from_image(
            image_bytes=data,
            config=cfg,
            expected_tg_username="benrenxing",
            shift_timezone="Asia/Bangkok",
        )
        dt = time.perf_counter() - t0
        ok_time = dt <= 25.0
        if err:
            status = f"FAIL [{err.error_code}]"
            if label.startswith("D_") and err.error_code == "AI_USER_OTHER_PERSON":
                status = f"OK(拒他人) [{err.error_code}]"
                ok_time = ok_time or dt <= 35.0
            elif label.startswith("F_"):
                ok_time = True  # 模拟图可能失败
            else:
                failed += 1
        else:
            status = f"PASS ident={ext.username_hint!r} clock={ext.clock_time!r}"
            if label.startswith("E_") and (ext.username_hint or "") != "benrenxing":
                status = "FAIL ident"
                failed += 1
        mark = "OK" if ok_time else "SLOW"
        print(f"  [{mark}] {label}: {dt:.1f}s {status}")

    print("\n完成。请重启 bot 后在群里实测。")
    return failed


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
