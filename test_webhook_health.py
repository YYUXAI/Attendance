from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager

import webhook_app


class HealthyCursor:
    def execute(self, sql):
        assert sql == "SELECT 1"

    def fetchone(self):
        return (1,)


def test_health_reports_only_components_started_by_webhook_process(monkeypatch):
    @contextmanager
    def cursor():
        yield HealthyCursor()

    monkeypatch.setattr(webhook_app, "get_cursor", cursor)
    monkeypatch.setenv("ATTENDANCE_WEBHOOK_RUN_WORKERS", "0")
    webhook_app.app.state.worker_tasks = []

    response = asyncio.run(webhook_app.health())
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["components"]["database"] is True
    assert payload["components"]["polling"] is False
    assert payload["components"]["workers"] == {
        "enabled": False,
        "running": 0,
        "failed": 0,
        "healthy": True,
    }


def test_health_fails_closed_when_database_is_unavailable(monkeypatch):
    @contextmanager
    def cursor():
        raise RuntimeError("db unavailable")
        yield

    monkeypatch.setattr(webhook_app, "get_cursor", cursor)
    monkeypatch.setenv("ATTENDANCE_WEBHOOK_RUN_WORKERS", "0")
    webhook_app.app.state.worker_tasks = []

    response = asyncio.run(webhook_app.health())
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["components"]["database"] is False
