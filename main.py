from __future__ import annotations

import os

# EasyOCR/PyTorch 与 NumPy(MKL) 同进程时须先于二者 import（见 Intel OpenMP #15）
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import asyncio

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from runtime import prepare_runtime, run_mode


async def main() -> None:
    mode = run_mode()
    if mode == "webhook":
        # Docker / Gateway 场景请用：uvicorn webhook_app:app --host 0.0.0.0 --port 8001
        raise SystemExit(
            "ATTENDANCE_RUN_MODE=webhook 时请启动 uvicorn webhook_app:app，"
            "不要直接 python main.py"
        )

    runtime = prepare_runtime(include_polling=True)
    await asyncio.gather(*runtime.workers)


if __name__ == "__main__":
    os.environ.setdefault("TZ", "UTC")
    asyncio.run(main())
