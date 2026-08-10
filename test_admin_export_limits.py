from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from gateway_provider.admin_export_module import prepare_three_csv_exports


class _PreflightCursor:
    def __init__(self, preflight_row: tuple[int, int]) -> None:
        self.preflight_row = preflight_row
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.full_query_started = False

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.executed.append((query, parameters))
        if "SELECT id, employee_id" in query and "export_rows" not in query:
            self.full_query_started = True

    def fetchone(self) -> tuple[int, int]:
        return self.preflight_row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


def test_admin_export_rejects_more_than_one_year_before_querying_rows() -> None:
    cursor = _PreflightCursor((0, 0))

    with pytest.raises(ValueError, match="日期范围不能超过 366 天"):
        prepare_three_csv_exports(
            cursor,  # type: ignore[arg-type]
            shift_id=12,
            start_date=date(2025, 1, 1),
            end_date=date(2026, 1, 2),
        )

    assert cursor.executed == []


def test_admin_export_rejects_excess_rows_during_preflight() -> None:
    cursor = _PreflightCursor((50_001, 1_000))

    with pytest.raises(ValueError, match="导出数据量过大"):
        prepare_three_csv_exports(
            cursor,  # type: ignore[arg-type]
            shift_id=12,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )

    assert len(cursor.executed) == 1
    assert cursor.full_query_started is False


def test_admin_export_rejects_excess_encoded_size_during_preflight() -> None:
    cursor = _PreflightCursor((1, 100_000_000))

    with pytest.raises(ValueError, match="导出数据量过大"):
        prepare_three_csv_exports(
            cursor,  # type: ignore[arg-type]
            shift_id=12,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )

    assert len(cursor.executed) == 1
    assert cursor.full_query_started is False
