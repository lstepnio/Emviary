import json
import logging
import math
from datetime import UTC, datetime, timedelta

import httpx

log = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 1_000_000


class Providers:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client

    def _json(self, method, url, **kwargs):
        client = self.client or httpx.Client(
            timeout=httpx.Timeout(12, connect=5), follow_redirects=False, trust_env=False
        )
        try:
            with client.stream(method, url, **kwargs) as response:
                response.raise_for_status()
                body = bytearray()
                for part in response.iter_bytes():
                    body.extend(part)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ValueError("Provider response exceeded the size limit")
                return json.loads(body)
        finally:
            if not self.client:
                client.close()

    def birds(self, site):
        payload = {
            "query": """query($period:InputDuration,$ne:InputLocation,$sw:InputLocation) {
                topBirdnetSpecies(limit:32,period:$period,ne:$ne,sw:$sw) {
                    count species { id commonName scientificName }
                }
            }""",
            "variables": {
                "period": {
                    "count": site.bird_lookback_hours,
                    "unit": "hours",
                    "timezone": site.timezone,
                },
                "ne": {
                    "lat": site.birdweather_bounds.northeast.latitude,
                    "lon": site.birdweather_bounds.northeast.longitude,
                },
                "sw": {
                    "lat": site.birdweather_bounds.southwest.latitude,
                    "lon": site.birdweather_bounds.southwest.longitude,
                },
            },
        }
        result = self._json("POST", "https://app.birdweather.com/graphql", json=payload)
        if result.get("errors"):
            raise ValueError("BirdWeather returned GraphQL errors")
        birds = []
        for entry in result["data"]["topBirdnetSpecies"]:
            species = entry["species"]
            count = int(entry["count"])
            if 0 <= count <= 1_000_000_000 and species.get("scientificName"):
                birds.append(
                    {
                        "scientific_name": species["scientificName"],
                        "common_name": species["commonName"],
                        "provider_id": str(species["id"]),
                        "count": count,
                    }
                )
        return {
            "provider": "birdweather",
            "birds": birds,
            "query": payload["variables"],
            "window_end": datetime.now(UTC).isoformat(),
            "window_hours": site.bird_lookback_hours,
            "regional": True,
        }

    def forecast(self, site, local_date):
        variables = [
            "weather_code",
            "temperature_2m_min",
            "temperature_2m_max",
            "precipitation_probability_max",
            "snowfall_sum",
            "wind_speed_10m_max",
        ]
        result = self._json(
            "GET",
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": site.weather_location.latitude,
                "longitude": site.weather_location.longitude,
                "timezone": site.timezone,
                "start_date": local_date,
                "end_date": local_date,
                "daily": ",".join(variables),
            },
        )
        if result.get("error") or result["daily"]["time"] != [local_date]:
            raise ValueError("Forecast date does not match the requested local day")
        units = result["daily_units"]
        if units["wind_speed_10m_max"] != "km/h" or units["snowfall_sum"] != "cm":
            raise ValueError("Unexpected forecast units")
        if units["temperature_2m_min"] != "°C" or units["temperature_2m_max"] != "°C":
            raise ValueError("Unexpected temperature units")
        values = {key: result["daily"][key][0] for key in variables}
        if any(v is None or not math.isfinite(v) for v in values.values()):
            raise ValueError("Incomplete forecast")
        return {
            "provider": "open_meteo",
            "local_date": local_date,
            "timezone": site.timezone,
            "units": units,
            "values": values,
        }

    def inputs(self, site, local_date, offline=False):
        results = {}
        flags = {
            "birdweather": site.providers.birdweather.enabled,
            "open_meteo": site.providers.open_meteo.enabled,
        }
        for provider, enabled in flags.items():
            if not enabled:
                continue
            cached = self.store.snapshot(site.id, provider, local_date)
            if cached:
                results[provider] = json.loads(cached["payload"])
                continue
            if not offline:
                try:
                    value = (
                        self.birds(site)
                        if provider == "birdweather"
                        else self.forecast(site, local_date)
                    )
                    self.store.save_snapshot(site.id, provider, local_date, value)
                    results[provider] = value
                    continue
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    log.warning("Provider %s unavailable: %s", provider, type(exc).__name__)
            # An old forecast never supplies weather for a different day.
            if provider == "birdweather":
                previous = self.store.snapshot(site.id, provider)
                if previous and datetime.fromisoformat(previous["received_at"]) > (
                    datetime.now(UTC) - timedelta(hours=48)
                ):
                    value = json.loads(previous["payload"])
                    value["cached_fallback"] = True
                    results[provider] = value
        return results
