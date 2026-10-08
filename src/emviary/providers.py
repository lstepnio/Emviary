import json
import logging
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 1_000_000


def distance_km(center, latitude, longitude):
    first, second = math.radians(center.latitude), math.radians(latitude)
    delta = math.radians(longitude - center.longitude)
    chord = (
        math.sin((second - first) / 2) ** 2
        + math.cos(first) * math.cos(second) * math.sin(delta / 2) ** 2
    )
    return 6371.0088 * 2 * math.atan2(math.sqrt(chord), math.sqrt(max(0, 1 - chord)))


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

    @staticmethod
    def contains(site, latitude, longitude):
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (latitude, longitude)):
            return False
        if site.bird_area == "colorado":
            bounds = site.locality_bounds
            return (
                bounds.southwest.latitude <= latitude <= bounds.northeast.latitude
                and bounds.southwest.longitude <= longitude <= bounds.northeast.longitude
            )
        return distance_km(site.weather_location, latitude, longitude) <= site.locality_radius_km

    def birds(self, site):
        bounds = site.locality_bounds
        period = {"count": site.bird_lookback_hours, "unit": "hours", "timezone": site.timezone}
        variables = {
            "period": period,
            "ne": {"lat": bounds.northeast.latitude, "lon": bounds.northeast.longitude},
            "sw": {"lat": bounds.southwest.latitude, "lon": bounds.southwest.longitude},
        }
        stations = self._json(
            "POST",
            "https://app.birdweather.com/graphql",
            json={
                "query": """query($period:InputDuration,$ne:InputLocation,$sw:InputLocation) {
                stations(first:100,period:$period,ne:$ne,sw:$sw) {
                    nodes { id coords { lat lon } }
                }
            }""",
                "variables": variables,
            },
        )
        if stations.get("errors"):
            raise ValueError("BirdWeather station lookup failed")
        station_ids = []
        for station in stations["data"]["stations"]["nodes"][:100]:
            coords = station["coords"]
            if self.contains(site, coords["lat"], coords["lon"]):
                station_ids.append(str(station["id"]))
        payload = {
            "query": """query($period:InputDuration,$stationIds:[ID!]!) {
                topSpecies(limit:32,period:$period,stationIds:$stationIds) {
                    count species { id commonName scientificName }
                }
            }""",
            "variables": {
                "period": period,
                "stationIds": station_ids,
            },
        }
        result = (
            self._json("POST", "https://app.birdweather.com/graphql", json=payload)
            if station_ids
            else {"data": {"topSpecies": []}}
        )
        if result.get("errors"):
            raise ValueError("BirdWeather returned GraphQL errors")
        birds = []
        for entry in result["data"]["topSpecies"]:
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
            "query": variables,
            "station_count": len(station_ids),
            "radius_km": site.locality_radius_km if site.bird_area == "local" else None,
            "bird_area": site.bird_area,
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

    def ebird(self, site):
        key_path = Path(os.getenv("EMVIARY_EBIRD_API_KEY_FILE", "/run/secrets/ebird-api-key"))
        key = key_path.read_text().strip()
        if not key or len(key) > 256:
            raise ValueError("eBird key file is empty or invalid")
        options = site.providers.ebird
        query = {
            "lat": site.weather_location.latitude,
            "lng": site.weather_location.longitude,
            "dist": site.locality_radius_km,
            "back": options.lookback_days,
            "maxResults": options.max_results,
            "includeProvisional": "false",
        }
        region = "US-CO" if site.bird_area == "colorado" else "geo"
        if site.bird_area == "colorado":
            for field in ("lat", "lng", "dist"):
                query.pop(field)
        result = self._json(
            "GET",
            f"https://api.ebird.org/v2/data/obs/{region}/recent",
            headers={"X-eBirdApiToken": key},
            params=query,
        )
        if not isinstance(result, list):
            raise ValueError("Unexpected eBird response")
        species = {}
        for entry in result[: options.max_results]:
            if not isinstance(entry, dict):
                raise ValueError("Unexpected eBird observation")
            name = entry.get("sciName")
            latitude, longitude = entry.get("lat"), entry.get("lng")
            if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
                continue
            if not math.isfinite(latitude) or not math.isfinite(longitude):
                continue
            if not self.contains(site, latitude, longitude):
                continue
            if isinstance(name, str) and 0 < len(name) <= 100:
                species.setdefault(
                    name.casefold(),
                    {
                        "scientific_name": name,
                        "common_name": str(entry.get("comName", ""))[:100],
                        "provider_id": str(entry.get("speciesCode", ""))[:32],
                        "last_observed": str(entry.get("obsDt", ""))[:32],
                    },
                )
        return {
            "provider": "ebird",
            "birds": list(species.values()),
            "query": query,
            "window_end": datetime.now(UTC).isoformat(),
            "regional": True,
            "evidence_type": "reported_presence",
        }

    def scope(self, site, provider):
        return {
            "version": 3,
            "center": site.weather_location.model_dump(),
            "radius_km": site.locality_radius_km if site.bird_area == "local" else None,
            "bird_area": site.bird_area,
            "timezone": site.timezone,
            "lookback": site.bird_lookback_hours
            if provider == "birdweather"
            else site.providers.ebird.lookback_days,
            "max_results": site.providers.ebird.max_results if provider == "ebird" else 32,
        }

    def inputs(self, site, local_date, offline=False):
        results = {}
        flags = {
            "birdweather": site.providers.birdweather.enabled,
            "open_meteo": site.providers.open_meteo.enabled,
            "ebird": site.providers.ebird.enabled,
        }
        for provider, enabled in flags.items():
            if not enabled:
                continue
            cached = self.store.snapshot(site.id, provider, local_date)
            if cached:
                value = json.loads(cached["payload"])
                if value.get("scope") == self.scope(site, provider):
                    results[provider] = value
                    continue
            if not offline:
                try:
                    if provider == "birdweather":
                        value = self.birds(site)
                    elif provider == "ebird":
                        value = self.ebird(site)
                    else:
                        value = self.forecast(site, local_date)
                    value["scope"] = self.scope(site, provider)
                    self.store.save_snapshot(site.id, provider, local_date, value)
                    results[provider] = value
                    continue
                except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
                    log.warning("Provider %s unavailable: %s", provider, type(exc).__name__)
            # An old forecast never supplies weather for a different day.
            if provider in ("birdweather", "ebird"):
                previous = self.store.snapshot(site.id, provider)
                if previous and datetime.fromisoformat(previous["received_at"]) > (
                    datetime.now(UTC) - timedelta(hours=48)
                ):
                    value = json.loads(previous["payload"])
                    if value.get("scope") == self.scope(site, provider):
                        value["cached_fallback"] = True
                        results[provider] = value
        return results
