# -*- coding: utf-8 -*-
"""打卡 OCR 全局线程池与并发上限（支持多人 1 分钟内同时发图）。"""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Callable, TypeVar

T = TypeVar("T")

_pool: ThreadPoolExecutor | None = None
_sem: asyncio.Semaphore | None = None


def ocr_max_concurrent() -> int:
    try:
        n = int(os.getenv("CHECKIN_AI_OCR_MAX_CONCURRENT", "2"))
    except ValueError:
        n = 2
    return max(1, min(n, 4))


def get_ocr_thread_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        workers = max(2, ocr_max_concurrent() + 1)
        _pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="checkin_ocr",
        )
    return _pool


def get_ocr_semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(ocr_max_concurrent())
    return _sem


async def run_ocr_cpu(fn: Callable[..., T], /, *args, **kwargs) -> T:
    """在共享 OCR 线程池中执行 CPU 密集任务（Tesseract 等）。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        get_ocr_thread_pool(), partial(fn, *args, **kwargs)
    )


def pool_map_first(
    fn: Callable[[str], T],
    keys: tuple[str, ...],
) -> T | None:
    """在共享池里并行跑多个 key，返回第一个非 None 结果。"""
    from concurrent.futures import as_completed

    pool = get_ocr_thread_pool()
    futures = {pool.submit(fn, k): k for k in keys}
    for fut in as_completed(futures):
        key = futures[fut]
        try:
            hit = fut.result()
        except Exception:
            continue
        if hit:
            return hit
    return None
