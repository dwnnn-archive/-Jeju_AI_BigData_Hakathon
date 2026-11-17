import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _ignore_local_env_file(monkeypatch):
    """로컬 backend/.env(실제 키)가 테스트 결과를 바꾸지 않도록 격리한다."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture(autouse=True)
def _archive_off_by_default(monkeypatch):
    """테스트가 실제 runtime 폴더에 예보 저장 파일을 만들지 않게 기본은 끈다.

    저장 장치를 시험하는 테스트가 직접 켠다.
    """
    monkeypatch.setenv("FORECAST_ARCHIVE_ENABLED", "false")


@pytest.fixture(autouse=True)
def _no_local_ev_snapshot(monkeypatch, tmp_path):
    """수집해 둔 실제 충전소 파일(runtime/ev_stations.json)이 배분 결과를 바꾸지 않게 격리한다."""
    monkeypatch.setenv("EV_SNAPSHOT_PATH", str(tmp_path / "no-ev-snapshot.json"))
    monkeypatch.setenv("EV_PROFILE_PATH", str(tmp_path / "no-ev-profile.json"))
