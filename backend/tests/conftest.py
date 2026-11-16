import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _ignore_local_env_file(monkeypatch):
    """로컬 backend/.env(실제 키)가 테스트 결과를 바꾸지 않도록 격리한다."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
