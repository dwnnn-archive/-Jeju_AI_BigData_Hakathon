from datetime import datetime

import httpx

from app.core.config import Settings
from app.domain.rules import evaluate
from app.providers import demo
from app.providers.kma import KST, KmaProvider
from app.providers.kma_nowcast import KmaNowcastProvider
from app.providers.kpx import KpxProvider
from app.repositories.forecasts import ForecastArchive
from app.tools.demand_model import JEJU_CITY_GRID, DemandModel
from app.tools.intraday import blend_weather, previous_evening_base
from app.tools.jeju_model import GOSAN_GRID, JejuModel
from app.tools.tool1_kma_weather import COORDINATES, GRID
from app.tools.tool2_predict_generation import (
    load_plants,
    model_prediction,
    physical_prediction,
)


class ToolBundle:
    def __init__(self, settings: Settings, clock=None):
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(KST))
        self._jeju_model: JejuModel | None = None
        self._demand_model: DemandModel | None = None
        self.archive: ForecastArchive | None = None
        if settings.forecast_archive_enabled:
            path = (
                settings.forecast_archive_path or settings.database_path.parent / "forecasts.sqlite"
            )
            self.archive = ForecastArchive(path)

    def now(self) -> datetime:
        return self.clock()

    @property
    def _recorder(self):
        return self.archive.safe_record_issue if self.archive else None

    def _model_info(self) -> dict:
        info: dict = {}
        if self._jeju_model is not None:
            meta = self._jeju_model.meta
            info["generation"] = {
                "wind_train_period": meta.get("wind", {}).get("train_period"),
                "solar_train_period": meta.get("solar", {}).get("train_period"),
            }
        if self._demand_model is not None:
            meta = self._demand_model.meta
            info["demand"] = {
                "train_period": meta.get("refit_period") or meta.get("train_period"),
                "refit_all": bool(meta.get("refit_all")),
            }
        return info

    def log_evaluation(self, run_id, phase, check_no, result, inputs=None) -> None:
        """판정 결과와 입력을 저장 장치에 남긴다(저장 실패는 분석을 막지 않는다)."""
        if self.archive:
            self.archive.safe_record_evaluation(
                run_id, phase, check_no, result, inputs, self._model_info()
            )

    def _fallback(self, reason, factory):
        if not self.settings.allow_mock_fallback:
            raise ValueError(reason)
        return factory(), {"source": "demo_fallback", "simulated": True, "reason": reason}

    def weather(self, request, refresh):
        if request.mode == "demo":
            return demo.weather(request.date), {"source": "demo", "simulated": True}
        key = self.settings.kma_api_key
        if not key or not key.get_secret_value():
            return self._fallback("kma_key_missing", lambda: demo.weather(request.date))
        try:
            with httpx.Client(timeout=self.settings.http_timeout) as client:
                rows = KmaProvider(
                    key.get_secret_value(),
                    client,
                    self.settings.kma_base_url,
                    self.settings.kma_auth_param,
                    recorder=self._recorder,
                ).fetch(request.date, *COORDINATES[request.region], grid=GRID[request.region])
            return rows, {"source": "kma", "simulated": False, "irradiance": "estimated"}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # Never include provider URLs, service keys or upstream response bodies in errors.
            return self._fallback("kma_unavailable_or_invalid", lambda: demo.weather(request.date))

    def demand(self, request):
        if request.mode == "demo":
            return demo.demand(request.date), {"source": "demo", "simulated": True}
        if not self.settings.kpx_url:
            if self.settings.jeju_demand_model_dir:
                return self._demand_model_demand(request)
            return self._fallback("kpx_url_missing", lambda: demo.demand(request.date))
        try:
            with httpx.Client(timeout=self.settings.http_timeout) as client:
                rows = KpxProvider(self.settings.kpx_url, client).fetch(request.date)
            return rows, {"source": "kpx_normalized_adapter", "simulated": False}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # 2중 안전: KPX 예측(중계)이 끊기면 자체 수요 모델이 이어받는다.
            # 모델도 없을 때만 시연값 대체(허용한 경우) 또는 명시적 실패.
            if self.settings.jeju_demand_model_dir:
                rows, source = self._demand_model_demand(request)
                return rows, {**source, "fallback_from": "kpx_unavailable_or_invalid"}
            return self._fallback("kpx_unavailable_or_invalid", lambda: demo.demand(request.date))

    def generation(self, request, weather, refresh):
        if request.mode == "demo":
            return demo.generation(request.date, request.scenario, refresh), {
                "source": "demo_scenario",
                "simulated": True,
                "model": "fixture",
            }
        if self.settings.jeju_model_dir:
            return self._jeju_model_generation(request, refresh)
        plants = load_plants(self.settings.plants_path, self.settings.corrections_path)
        wind = sum(p.capacity_mw for p in plants if p.kind == "wind")
        solar = sum(p.capacity_mw for p in plants if p.kind == "solar")
        source = {
            "source": "prediction",
            "simulated": any(p.source == "demo" for p in plants),
            "model": "xgboost" if self.settings.model_path else "physical_estimate",
            "capacity_sources": sorted({p.source for p in plants}),
            "validated": False,
        }
        if self.settings.model_path:
            rows = model_prediction(self.settings.model_path, weather, wind, solar)
        else:
            rows = physical_prediction(weather, wind, solar)
        return rows, source

    def _gosan_weather(self, request, base=None):
        """제주 전체 모델의 입력: 학습과 같은 지점(고산)의 단기예보 격자."""
        key = self.settings.kma_api_key
        if not key or not key.get_secret_value():
            raise ValueError("kma_key_missing")
        with httpx.Client(timeout=self.settings.http_timeout) as client:
            return KmaProvider(
                key.get_secret_value(),
                client,
                self.settings.kma_base_url,
                self.settings.kma_auth_param,
                recorder=self._recorder,
            ).fetch(request.date, *COORDINATES["jeju"], grid=GOSAN_GRID, base=base)

    def _jeju_model_generation(self, request, refresh):
        try:
            weather = self._gosan_weather(request)
            if self._jeju_model is None:
                self._jeju_model = JejuModel(self.settings.jeju_model_dir)
            rows = self._jeju_model.predict(weather)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError, ImportError):
            # Never include provider URLs, service keys or upstream response bodies in errors.
            return self._fallback(
                "jeju_model_unavailable_or_invalid",
                lambda: demo.generation(request.date, request.scenario, refresh),
            )
        return rows, {
            "source": "prediction",
            "simulated": False,
            "model": "xgboost_jeju_total",
            "target": "KPX 제주 전체 시장 거래 발전량(ESS 포함)",
            "weather_grid": "gosan",
            "capacity_sources": [],
            "validated": False,
        }

    def _jeju_city_weather(self, request, base=None):
        """수요 모델의 입력: 학습과 같은 지점(제주시)의 단기예보 격자."""
        key = self.settings.kma_api_key
        if not key or not key.get_secret_value():
            raise ValueError("kma_key_missing")
        with httpx.Client(timeout=self.settings.http_timeout) as client:
            return KmaProvider(
                key.get_secret_value(),
                client,
                self.settings.kma_base_url,
                self.settings.kma_auth_param,
                recorder=self._recorder,
            ).fetch(request.date, *COORDINATES["jeju"], grid=JEJU_CITY_GRID, base=base)

    def _demand_model_demand(self, request):
        try:
            weather = self._jeju_city_weather(request)
            if self._demand_model is None:
                self._demand_model = DemandModel(self.settings.jeju_demand_model_dir)
            rows = self._demand_model.predict(weather)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError, ImportError):
            # Never include provider URLs, service keys or upstream response bodies in errors.
            return self._fallback(
                "demand_model_unavailable_or_invalid", lambda: demo.demand(request.date)
            )
        return rows, {
            "source": "demand_model",
            "simulated": False,
            "model": "xgboost_jeju_demand",
            "target": "KPX 제주 발전단 수요 예측(자체 모델)",
            "weather_grid": "jeju_city",
            "validated": False,
        }

    # ---- 당일 점검 (초단기실황·초단기예보) ----

    def _nowcast(self, grid, now):
        """(초단기실황, 이후 6시간 초단기예보). 키가 없거나 호출이 실패하면 예외를 그대로 낸다."""
        key = self.settings.kma_api_key
        if not key or not key.get_secret_value():
            raise ValueError("kma_key_missing")
        with httpx.Client(timeout=self.settings.http_timeout) as client:
            provider = KmaNowcastProvider(
                key.get_secret_value(),
                client,
                self.settings.kma_base_url,
                self.settings.kma_auth_param,
                recorder=self._recorder,
            )
            return provider.observation(*grid, now), provider.forecast(*grid, now)

    def _load_generation_model(self):
        if not self.settings.jeju_model_dir:
            raise ValueError("jeju_model_dir_missing")
        if self._jeju_model is None:
            self._jeju_model = JejuModel(self.settings.jeju_model_dir)
        return self._jeju_model

    def _load_demand_model(self):
        if not self.settings.jeju_demand_model_dir:
            raise ValueError("jeju_demand_model_dir_missing")
        if self._demand_model is None:
            self._demand_model = DemandModel(self.settings.jeju_demand_model_dir)
        return self._demand_model

    def intraday_check(self, request, now, day_ahead_base=None):
        """하루 전 예보(전날 23시 발표)에 초단기실황·초단기예보를 덧씌워 당일 위험을 다시 판정한다.

        시연값이나 다른 값으로 조용히 대체하지 않는다. 입력이 하나라도 없으면 예외를 낸다.
        반환값의 inputs 는 나중에 예보 정확도를 평가할 수 있도록 저장할 수 있는 입력 기록이다.
        """
        target, now = request.date, now.astimezone(KST)
        base = day_ahead_base or previous_evening_base(target)
        gen_model, demand_model = self._load_generation_model(), self._load_demand_model()
        day_gen = self._gosan_weather(request, base=base)
        day_dem = self._jeju_city_weather(request, base=base)
        obs_g, ultra_g = self._nowcast(GOSAN_GRID, now)
        obs_c, ultra_c = self._nowcast(JEJU_CITY_GRID, now)
        gen_weather, sources = blend_weather(day_gen, obs_g, ultra_g, target)
        dem_weather, _ = blend_weather(day_dem, obs_c, ultra_c, target)
        result = evaluate(
            gen_model.predict(gen_weather), demand_model.predict(dem_weather), target, now.hour
        )
        return {
            "result": result,
            "inputs": {
                "checked_at": now.isoformat(),
                "from_hour": now.hour,
                "day_ahead_base": list(base),
                "sources": {str(h): v for h, v in sources.items()},
                "generation_weather": [w.model_dump(mode="json") for w in gen_weather],
                "demand_weather": [w.model_dump(mode="json") for w in dem_weather],
            },
        }
