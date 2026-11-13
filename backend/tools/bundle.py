import httpx

from backend.core.config import Settings
from backend.providers import demo
from backend.providers.kma import KmaProvider
from backend.providers.kpx import KpxProvider
from backend.tools.tool1_kma_weather import COORDINATES
from backend.tools.tool2_predict_generation import (
    load_plants,
    model_prediction,
    physical_prediction,
)


class ToolBundle:
    def __init__(self, settings: Settings):
        self.settings = settings

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
                rows = KmaProvider(key.get_secret_value(), client).fetch(
                    request.date, *COORDINATES[request.region]
                )
            return rows, {"source": "kma", "simulated": False, "irradiance": "estimated"}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # Never include provider URLs, service keys or upstream response bodies in errors.
            return self._fallback("kma_unavailable_or_invalid", lambda: demo.weather(request.date))

    def demand(self, request):
        if request.mode == "demo":
            return demo.demand(request.date), {"source": "demo", "simulated": True}
        if not self.settings.kpx_url:
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
