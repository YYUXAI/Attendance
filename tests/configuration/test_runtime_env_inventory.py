from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIRECTORIES = ("gateway_provider", "infra", "services", "tasks", "repositories", "domain")
PATTERNS = (
    re.compile(r'(?:os\.getenv|os\.environ\.get)\(\s*["\']([A-Z][A-Z0-9_]*)["\']'),
    re.compile(r'os\.environ\[\s*["\']([A-Z][A-Z0-9_]*)["\']\s*\]'),
    re.compile(r'environment\.get\(\s*["\']([A-Z][A-Z0-9_]*)["\']'),
    re.compile(r'(?:_required|_enabled|_required_environment)\(\s*environment,\s*["\']([A-Z][A-Z0-9_]*)["\']'),
    re.compile(r'_required_environment\(\s*["\']([A-Z][A-Z0-9_]*)["\']'),
)


def test_inventory_classifies_every_long_running_environment_key_once() -> None:
    inventory = _inventory()
    classified = [
        name
        for names in inventory["categories"].values()
        for name in names
    ]
    assert [name for name, count in Counter(classified).items() if count != 1] == []
    assert sorted(classified) == sorted(_runtime_environment_keys())


def test_private_and_business_truth_never_appear_in_public_category() -> None:
    categories = _inventory()["categories"]
    public = set(categories["public"])
    assert public.isdisjoint(categories["sensitive_secret"])
    assert public.isdisjoint(categories["sensitive_identifier"])
    assert public.isdisjoint(categories["business_database_truth"])
    assert all("DATABASE_URL" not in name for name in public)
    assert all("BEARER_TOKEN" not in name for name in public)
    assert all("SIGNING_SECRET" not in name for name in public)
    assert all("CHAT_ID" not in name for name in public)
    assert all("SPREADSHEET_ID" not in name for name in public)


def _inventory() -> dict[str, object]:
    return json.loads(
        (ROOT / "config" / "legacy-runtime-env-inventory.json").read_text(encoding="utf-8")
    )


def _runtime_environment_keys() -> set[str]:
    files = [
        path
        for directory in RUNTIME_DIRECTORIES
        for path in (ROOT / directory).rglob("*.py")
    ]
    files.extend((ROOT / name) for name in ("shift_web_app.py", "runtime-secret-entrypoint.py"))
    found: set[str] = set()
    for path in files:
        source = path.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            found.update(pattern.findall(source))
    return found
