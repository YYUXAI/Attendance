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
