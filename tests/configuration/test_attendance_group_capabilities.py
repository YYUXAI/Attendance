from __future__ import annotations

import json

import pytest

from infra.attendance_group_policy import KNOWN_CAPABILITIES, title_has_capability
from infra.bbq_google_sheets_config import is_bbq_chat
from infra.checkin_ai_config import premium_zhipu_enabled
from infra.checkin_employee_id_only_config import requires_employee_id_only_checkin
from infra.checkin_pc_only_config import requires_pc_screenshot
from infra.checkin_remote_diff_config import requires_remote_diff_checkin
from infra.checkin_visible_texts_config import visible_texts_identity_enabled
from infra.test_group_google_config import is_test_group_chat
from infra.ux_assistant_attendance_test_group_config import (
    is_ux_assistant_attendance_test_group,
)
from services.checkin_service import (
    formal_group_roster_source_for_chat,
    should_run_ai_without_persist,
)
from services.leave_flow_guard import (
    requires_leave_back_copy_fallback,
    requires_leave_mutual_exclusion,
)


TITLE = "configured attendance group"


def _configure(monkeypatch: pytest.MonkeyPatch, *capabilities: str, roster: str = "main") -> None:
    monkeypatch.setenv(
        "ATTENDANCE_GROUPS_JSON",
        json.dumps(
            [{"title": TITLE, "roster": roster, "capabilities": list(capabilities)}],
            separators=(",", ":"),
        ),
    )
    monkeypatch.setenv("CHECKIN_AI_PREMIUM_ENABLED", "true")


@pytest.mark.parametrize("capability", sorted(KNOWN_CAPABILITIES))
def test_each_declared_group_capability_is_visible_and_other_groups_are_closed(
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    _configure(monkeypatch, capability)
    assert title_has_capability(TITLE, capability)
    assert not title_has_capability("ordinary group", capability)


def test_runtime_feature_adapters_share_the_single_title_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, "premium-ai")
    assert premium_zhipu_enabled(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, "remote-diff-checkin")
    assert requires_remote_diff_checkin(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, "employee-id-only-checkin")
    assert requires_employee_id_only_checkin(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, "pc-only-screenshot")
    assert requires_pc_screenshot(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, "visible-texts-identity-correction")
    assert visible_texts_identity_enabled(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, "ai-dry-run-no-persist")
    assert should_run_ai_without_persist(
        chat_id=1,
        employee_id="fixture-employee",
        roster_allowed=False,
        chat_title=TITLE,
    )
    _configure(monkeypatch, "test-group-google-sheets")
    assert is_test_group_chat(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, "leave-mutual-exclusion")
    assert requires_leave_mutual_exclusion(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, "leave-back-copy-fallback")
    assert requires_leave_back_copy_fallback(chat_id=1, chat_title=TITLE)
    _configure(monkeypatch, roster="alt")
    assert formal_group_roster_source_for_chat(chat_id=1, chat_title=TITLE) == "alt"


def test_bbq_capability_supports_multiple_groups_without_a_single_chat_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ATTENDANCE_GROUPS_JSON",
        json.dumps([
            {"title": "bbq one", "roster": "main", "capabilities": ["bbq-google-sheets"]},
            {"title": "bbq two", "roster": "alt", "capabilities": ["bbq-google-sheets"]},
        ]),
    )
    assert is_bbq_chat(chat_id=100, chat_title="bbq one")
    assert is_bbq_chat(chat_id=200, chat_title="bbq two")
    assert not is_bbq_chat(chat_id=100, chat_title="ordinary")


def test_removed_group_and_numeric_id_alone_never_retain_attendance_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTENDANCE_GROUPS_JSON", "[]")
    assert not requires_remote_diff_checkin(chat_id=-100123, chat_title=TITLE)
    assert not requires_pc_screenshot(chat_id=-100123, chat_title=TITLE)
    assert formal_group_roster_source_for_chat(chat_id=-100123, chat_title=TITLE) is None


def test_ux_assistant_attendance_test_group_runs_ai_dry_run_outside_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, "standard-checkin")
    assert is_ux_assistant_attendance_test_group(
        chat_id=-1004347063533,
        chat_title="ux助手考勤测试群",
    )
    assert should_run_ai_without_persist(
        chat_id=-1004347063533,
        employee_id="99999",
        roster_allowed=False,
        chat_title="ux助手考勤测试群",
    )
    assert not should_run_ai_without_persist(
        chat_id=-1004347063533,
        employee_id="99999",
        roster_allowed=True,
        chat_title="ux助手考勤测试群",
    )
    assert not should_run_ai_without_persist(
        chat_id=-100123,
        employee_id="99999",
        roster_allowed=False,
        chat_title="ordinary group",
    )


def test_quality_inspection_uses_base_zhipu_flash_not_premium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from infra.checkin_ai_config import (
        CheckinAiConfig,
        base_zhipu_config_for_quality_inspection,
        resolve_checkin_ai_config_for_chat,
    )

    monkeypatch.setenv(
        "ATTENDANCE_GROUPS_JSON",
        json.dumps([
            {
                "title": "ux助手考勤测试群",
                "roster": "main",
                "capabilities": ["premium-ai"],
            }
        ]),
    )
    monkeypatch.setenv("CHECKIN_AI_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("CHECKIN_AI_MODEL", "glm-4v-flash")
    monkeypatch.setenv("CHECKIN_AI_API_KEY", "base-key")
    monkeypatch.setenv("CHECKIN_AI_PREMIUM_API_KEY", "premium-key")
    monkeypatch.setenv("CHECKIN_AI_PREMIUM_MODEL", "glm-4.6v")
    base = CheckinAiConfig(
        enabled=True,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="base-key",
        model="glm-4v-flash",
        mode="required",
        max_clock_skew_minutes=30,
        timeout_seconds=180.0,
        trust_sender_when_name_unreadable=False,
        name_verify_mode="vision",
        extract_backend="zhipu",
        clock_fallback_send_time=False,
        text_model="glm-4v-flash",
    )
    qc = base_zhipu_config_for_quality_inspection(base)
    assert qc.model == "glm-4v-flash"
    assert qc.api_key == "base-key"
    premium = resolve_checkin_ai_config_for_chat(
        base,
        chat_id=-1004347063533,
        chat_title="ux助手考勤测试群",
    )
    assert premium.model == "glm-4.6v"
    assert premium.api_key == "premium-key"
    assert qc == base_zhipu_config_for_quality_inspection(
        replace(base, api_key="premium-key", model="glm-4.6v")
    )
