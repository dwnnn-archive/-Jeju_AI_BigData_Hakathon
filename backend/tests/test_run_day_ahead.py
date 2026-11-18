from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.providers.kma import KST
from scripts.run_day_ahead import (
    EXIT_OK,
    idempotency_key,
    run_day_ahead,
    target_for,
)


def at(hour, minute, day=18):
    return datetime(2026, 11, day, hour, minute, tzinfo=KST)


def test_target_is_tomorrow_only_inside_the_window():
    assert target_for(at(17, 30)) == date(2026, 11, 19)
    assert target_for(at(17, 15)) == date(2026, 11, 19)
    assert target_for(at(23, 50)) == date(2026, 11, 19)
    assert target_for(at(17, 14)) is None
    assert target_for(at(23, 51)) is None
    assert target_for(at(2, 15)) is None
    assert target_for(at(23, 30, day=30)) == date(2026, 12, 1)


def test_idempotency_key_is_stable_and_retry_differs():
    d = date(2026, 11, 19)
    assert idempotency_key(d, "jeju", "live") == idempotency_key(d, "jeju", "live")
    assert idempotency_key(d, "jeju", "live") != idempotency_key(d, "jeju", "demo")
    assert idempotency_key(d, "jeju", "live") != idempotency_key(date(2026, 11, 20), "jeju", "live")
    assert idempotency_key(d, "jeju", "live") != idempotency_key(d, "jeju", "live", attempt=1)


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "state.sqlite",
        forecast_archive_enabled=True,
        forecast_archive_path=tmp_path / "forecasts.sqlite",
    )
    with TestClient(create_app(settings)) as value:
        yield value


def test_running_twice_for_the_same_day_makes_one_run(client):
    target = date(2026, 11, 19)
    code1, first = run_day_ahead(client, target, mode="demo", poll=0.05)
    code2, second = run_day_ahead(client, target, mode="demo", poll=0.05)
    assert code1 == code2 == EXIT_OK
    assert first["id"] == second["id"]
    assert first["target"] == "2026-11-19"
    assert first["status"] in ("completed", "awaiting_approval")
    assert len(client.get("/api/v1/analyses").json()) == 1
