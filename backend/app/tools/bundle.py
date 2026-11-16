import httpx

from app.core.config import Settings
from app.providers import demo
from app.providers.kma import KmaProvider
from app.providers.kpx import KpxProvider
from app.tools.demand_model import JEJU_CITY_GRID, DemandModel
from app.tools.jeju_model import GOSAN_GRID, JejuModel
from app.tools.tool1_kma_weather import COORDINATES, GRID
from app.tools.tool2_predict_generation import (
    load_plants,
    model_prediction,
    physical_prediction,
)


class ToolBundle:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jeju_model: JejuModel | None = None
        self._demand_model: DemandModel | None = None

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

    def _gosan_weather(self, request):
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
            ).fetch(request.date, *COORDINATES["jeju"], grid=GOSAN_GRID)

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

    def _jeju_city_weather(self, request):
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
            ).fetch(request.date, *COORDINATES["jeju"], grid=JEJU_CITY_GRID)

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
