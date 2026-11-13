from datetime import date

import httpx

from backend.domain.schemas import EnergyHour, validate_day


class KpxProvider:
    """Consumes the documented normalized KPX adapter contract, not an invented public API."""

    def __init__(self, url: str, client: httpx.Client):
        if not url.startswith("https://"):
            raise ValueError("KPX adapter URL must use HTTPS")
        self.url, self.client = url, client

    def fetch(self, target: date) -> list[EnergyHour]:
        response = self.client.get(self.url, params={"date": target.isoformat(), "region": "jeju"})
        response.raise_for_status()
        return validate_day(
            [EnergyHour.model_validate(r) for r in response.json()["hours"]], target
        )
