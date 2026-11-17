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
    # 제주데이터허브 '전기자동차 충전소 정보' API. 프로젝트 키는 허브 마이페이지에서 발급한다.
    jejuhub_project_key: SecretStr | None = None
    # 수집한 충전소 목록 저장 위치. 배분은 이 파일을 읽는다(네트워크 호출 없음).
    ev_snapshot_path: Path = ROOT / "runtime/ev_stations.json"
    # 충전 이력(월별·요일별 API)으로 만든 이용 패턴. 있으면 가정값 대신 쓴다.
    ev_profile_path: Path = ROOT / "runtime/ev_profile.json"
    ev_slow_kw: float = Field(default=7.0, gt=0, le=50)
    ev_fast_kw: float = Field(default=50.0, gt=0, le=350)
    ev_idle_ratio: float = Field(default=0.5, ge=0, le=1)
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
    # 통보문 초안을 LLM이 문장으로 쓰게 한다. 키가 없으면 템플릿 초안(수치는 코드가 계산).
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_timeout: float = Field(default=30, gt=0, le=120)
    notification_mode: Literal["mock", "webhook"] = "mock"
    notification_url: str | None = None
    notification_token: SecretStr | None = None
    http_timeout: float = Field(default=10, gt=0, le=60)
