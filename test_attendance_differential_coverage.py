from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.parity.run_attendance_differential import (
    load_attendance_matrix,
    normalize_markup,
)


def test_markup_normalization_preserves_exact_button_payloads() -> None:
    assert normalize_markup(
        {
            "inlineKeyboard": [[
                {"text": "注册", "callbackData": "att:register"},
                {
                    "text": "签到",
                    "switchInlineQueryCurrentChat": "#打卡\n事项：签到",
                },
                {"text": "复制", "copyText": "#打卡\n事项：签到"},
                {
                    "text": "班表",
                    "webAppUrl": "https://attendance.example.test/shift-app/",
                },
            ]]
        }
    ) == {
        "kind": "INLINE_KEYBOARD",
        "rows": [[
            {"text": "注册", "action": "CALLBACK", "value": "att:register"},
            {
                "text": "签到",
                "action": "SWITCH_INLINE_QUERY_CURRENT_CHAT",
                "value": "#打卡\n事项：签到",
            },
            {
                "text": "复制",
                "action": "COPY_TEXT",
                "value": "#打卡\n事项：签到",
            },
            {
                "text": "班表",
                "action": "WEB_APP",
                "value": "https://attendance.example.test/shift-app/",
            },
        ]],
    }

    assert normalize_markup(
        {
            "inline_keyboard": [[
                {"text": "注册", "callback_data": "reg:begin"},
                {"text": "个人", "callback_data": "profile:myinfo"},
                {"text": "导出", "callback_data": "act:export"},
            ]]
        }
    ) == {
        "kind": "INLINE_KEYBOARD",
        "rows": [[
            {"text": "注册", "action": "CALLBACK", "value": "att:register"},
            {"text": "个人", "action": "CALLBACK", "value": "att:profile"},
            {"text": "导出", "action": "CALLBACK", "value": "att:export"},
        ]],
    }


def test_attendance_differential_executes_every_matrix_scenario() -> None:
    old_root_value = os.environ.get("ATTENDANCE_PARITY_OLD_ROOT")
    matrix_value = os.environ.get("ATTENDANCE_PARITY_MATRIX")
    old_database_url = os.environ.get("ATTENDANCE_PARITY_OLD_DATABASE_URL")
    current_database_url = os.environ.get(
        "ATTENDANCE_PARITY_CURRENT_DATABASE_URL"
    )
    if (
        not old_root_value
        or not matrix_value
        or not old_database_url
        or not current_database_url
    ):
        pytest.skip(
            "set ATTENDANCE_PARITY_OLD_ROOT, ATTENDANCE_PARITY_MATRIX, and "
            "isolated old/current database URLs "
            "for the cross-version parity gate"
        )

    root = Path(__file__).resolve().parent
    old_root = Path(old_root_value).resolve()
    matrix_path = Path(matrix_value).resolve()
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/parity/run_attendance_differential.py"),
            "--old-root",
            str(old_root),
            "--python",
            sys.executable,
            "--matrix",
            str(matrix_path),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)

    expected = _attendance_matrix(matrix_path)
    expected_ids = sorted(item["scenarioId"] for item in expected)
    assert len(expected_ids) == 104
    assert sum(item["classification"] == "PARITY" for item in expected) == 89
    assert sum(item["classification"] == "BUGFIX_DELTA" for item in expected) == 15
    assert report["scenarioIds"] == expected_ids
    assert report["counts"] == {
        "BUGFIX_DELTA": 15,
        "PARITY": 89,
        "TOTAL": 104,
    }
    assert report["result"] == "PASS"

    evidence = report["evidence"]
    assert sorted(evidence) == expected_ids
    for item in expected:
        scenario_id = item["scenarioId"]
        proof = evidence[scenario_id]
        assert proof["classification"] == item["classification"]
        assert proof["exactInput"] == item["exactInput"]
        assert proof["oldCharacterizationExecuted"] is True
        assert proof["currentExecutionExecuted"] is True
        if item["classification"] == "PARITY":
            assert proof["sameInput"] is True
            assert proof["traceEqual"] is True
        else:
            assert proof["oldDeploymentClaimed"] is False
            assert proof["oldLockedBaselineExecuted"] is True
            assert proof["oldFailureReproduced"] is True
            assert proof["currentRecoveryTestPassed"] is True


def _attendance_matrix(matrix_path: Path) -> list[dict[str, object]]:
    return [
        {
            "scenarioId": item["scenarioId"],
            "classification": item["classification"],
            "exactInput": item["exactInput"],
        }
        for item in load_attendance_matrix(matrix_path)
    ]
