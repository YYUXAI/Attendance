# -*- coding: utf-8 -*-
"""兼容入口：请改用 scripts/checkin_ai_selftest.py"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "checkin_ai_selftest.py"
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
