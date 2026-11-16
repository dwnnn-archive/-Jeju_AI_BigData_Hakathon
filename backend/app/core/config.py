from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)
    database_path: Path = ROOT / "runtime/jeju.sqlite"
    api_token: SecretStr | None = None
    approver_token: SecretStr | None = None
    approver_id: str = "local-officer"
    kma_api_key: SecretStr | None = None
    kma_base_url: str = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"
    # 가이드의 요청 명세표는 serviceKey, 예제 URL은 authKey로 표기가 달라 설정으로 열어 둔다.
    kma_auth_param: Literal["authKey", "serviceKey"] = "authKey"
    asos_api_key: SecretStr | None = None  # 학습용 과거 실측 기상(ASOS). 디코딩된 키.
    kpx_gen_api_key: SecretStr | None = None  # KPX 지역별 시간별 태양광·풍력 발전량(odcloud)
    kpx_url: str | None = None
    allow_mock_fallback: bool = False
    # 예보 저장 장치: 받은 예보 원본과 판정 기록을 쌓는다.
    # 기본은 켜짐이고 경로는 DB 파일 옆 forecasts.sqlite 다.
    forecast_archive_enabled: bool = True
    forecast_archive_path: Path | None = None
    worker_enabled: bool = True
    heartbeat_seconds: float = Field(default=2, ge=0.1, le=5)
    worker_stale_seconds: float = Field(default=10, ge=10, le=60)
    result_ttl_seconds: int = Field(default=3600, ge=1, le=86400)
    max_refreshes: int = Field(default=1, ge=0, le=3)
    max_intraday_checks: int = Field(default=2, ge=0, le=6)
    plants_path: Path = ROOT / "data/fixtures/plants.json"
    corrections_path: Path = ROOT / "data/corrections/plants.json"
    model_path: Path | None = None
    # 제주 전체 단위 모델 폴더(wind.json, solar.json, meta.json). 설정하면 live 발전량 예측에 쓴다.
    jeju_model_dir: Path | None = None
    # 제주 수요 예측 모델 폴더(demand.json, meta.json). KPX_URL(중계)이 없을 때 live 수요에 쓴다.
    jeju_demand_model_dir: Path | None = None
    notification_mode: Literal["mock", "webhook"] = "mock"
    notification_url: str | None = None
    notification_token: SecretStr | None = None
    http_timeout: float = Field(default=10, gt=0, le=60)
