"""Validated public Attendance group policy, keyed by Telegram group title.

The public manifest never contains numeric chat IDs. Gateway owns title-to-route/ID
discovery; Attendance uses the same title policy for behavior selection.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


STANDARD_CAPABILITY = "standard-checkin"
KNOWN_CAPABILITIES = frozenset(
    {
        STANDARD_CAPABILITY,
        "premium-ai",
        "remote-diff-checkin",
        "employee-id-only-checkin",
        "pc-only-screenshot",
        "visible-texts-identity-correction",
        "ai-dry-run-no-persist",
        "test-group-google-sheets",
        "bbq-google-sheets",
        "leave-mutual-exclusion",
        "leave-back-copy-fallback",
        "export-scope",
    }
)
KNOWN_ROSTERS = frozenset({"main", "alt"})
CONFLICTING_CAPABILITY_SETS = (
    frozenset({STANDARD_CAPABILITY, "remote-diff-checkin"}),
    frozenset({"test-group-google-sheets", "bbq-google-sheets"}),
    frozenset({"ai-dry-run-no-persist", "test-group-google-sheets"}),
    frozenset({"ai-dry-run-no-persist", "bbq-google-sheets"}),
)


@dataclass(frozen=True)
class AttendanceGroupPolicy:
    title: str
    roster: str
    capabilities: frozenset[str]

    def has(self, capability: str) -> bool:
        return capability in self.capabilities


def normalize_group_policies(value: object) -> tuple[AttendanceGroupPolicy, ...]:
    if not isinstance(value, list):
        raise ValueError("Attendance groups must be a list")
    policies: list[AttendanceGroupPolicy] = []
    seen_titles: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"Attendance group {index} must be an object")
        if set(item) - {"title", "roster", "capabilities"}:
            raise ValueError(f"Attendance group {index} contains unknown fields")
        title = item.get("title")
        roster = item.get("roster")
        capabilities_value = item.get("capabilities", [STANDARD_CAPABILITY])
        if not isinstance(title, str) or title != title.strip() or not title:
            raise ValueError(f"Attendance group {index} has an invalid title")
        if title in seen_titles:
            raise ValueError(f"Duplicate Attendance group title: {title}")
        if roster not in KNOWN_ROSTERS:
            raise ValueError(f"Attendance group {title} has an invalid roster")
        if not isinstance(capabilities_value, list) or not all(
            isinstance(item, str) for item in capabilities_value
        ):
            raise ValueError(f"Attendance group {title} capabilities must be a list")
        if len(capabilities_value) != len(set(capabilities_value)):
            raise ValueError(f"Attendance group {title} has duplicate capabilities")
        capabilities = frozenset(capabilities_value or [STANDARD_CAPABILITY])
        unknown = capabilities - KNOWN_CAPABILITIES
        if unknown:
            raise ValueError(f"Attendance group {title} has unknown capabilities")
        for conflict in CONFLICTING_CAPABILITY_SETS:
            if conflict <= capabilities:
                raise ValueError(f"Attendance group {title} has conflicting capabilities")
        seen_titles.add(title)
        policies.append(
            AttendanceGroupPolicy(
                title=title,
                roster=str(roster),
                capabilities=capabilities,
            )
        )
    return tuple(policies)


def public_group_values(
    policies: Iterable[AttendanceGroupPolicy],
) -> list[dict[str, object]]:
    return [
        {
            "title": policy.title,
            "roster": policy.roster,
            "capabilities": sorted(policy.capabilities),
        }
        for policy in policies
    ]


def group_policy_fingerprint(policies: Iterable[AttendanceGroupPolicy]) -> str:
    canonical = json.dumps(
        public_group_values(policies),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_group_policies(environment: Mapping[str, str]) -> tuple[AttendanceGroupPolicy, ...]:
    raw = environment.get("ATTENDANCE_GROUPS_JSON")
    if raw is None:
        raise RuntimeError("ATTENDANCE_GROUPS_JSON is required")
    try:
        value: Any = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("ATTENDANCE_GROUPS_JSON is invalid") from error
    try:
        return normalize_group_policies(value)
    except ValueError as error:
        raise RuntimeError("ATTENDANCE_GROUPS_JSON is invalid") from error


def policy_for_title(
    policies: Iterable[AttendanceGroupPolicy],
    title: str | None,
) -> AttendanceGroupPolicy | None:
    if not title:
        return None
    return next((policy for policy in policies if policy.title == title), None)


def configured_policy_for_title(title: str | None) -> AttendanceGroupPolicy | None:
    import os

    return policy_for_title(load_group_policies(os.environ), title)


def title_has_capability(title: str | None, capability: str) -> bool:
    policy = configured_policy_for_title(title)
    return bool(policy and policy.has(capability))
