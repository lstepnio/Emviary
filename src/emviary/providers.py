import json
import logging
import math
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .status_data import json_object, timestamp
from .weather import combine_forecasts, nws_forecast, validate_forecast

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
                "hourly": "weather_code,is_day",
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
        hourly = result["hourly"]
        times, codes, days = (hourly[key] for key in ("time", "weather_code", "is_day"))
        if not times or len(times) != len(codes) or len(times) != len(days):
            raise ValueError("Incomplete hourly forecast")
        daylight = []
        for time, code, day in zip(times, codes, days, strict=True):
            if not time.startswith(local_date + "T") or day not in (0, 1):
                raise ValueError("Invalid hourly forecast day")
            if code is None or not math.isfinite(code):
                raise ValueError("Incomplete hourly weather code")
            if day:
                daylight.append(int(code))
        if not daylight:
            raise ValueError("No daylight forecast hours")
        # Summarize prevailing daylight sky, not the worst hour of a 24-hour day.
        # Ties favor the cloudier code; daily precipitation/storm cues remain intact.
        sky = Counter(code for code in daylight if code in (0, 1, 2, 3, 45, 48))
        if sky:
            values["daylight_weather_code"] = max(sky, key=lambda code: (sky[code], code))
        return validate_forecast(
            {
                "provider": "open_meteo",
                "local_date": local_date,
                "timezone": site.timezone,
                "units": units,
                "values": values,
            },
            local_date,
        )

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
            "version": 5 if provider in ("open_meteo", "nws") else 3,
            "center": site.weather_location.model_dump(),
            "radius_km": site.locality_radius_km if site.bird_area == "local" else None,
            "bird_area": site.bird_area,
            "timezone": site.timezone,
            "lookback": site.bird_lookback_hours
            if provider == "birdweather"
            else site.providers.ebird.lookback_days,
            "max_results": site.providers.ebird.max_results if provider == "ebird" else 32,
        }

    def nws(self, site, local_date, now):
        headers = {
            "User-Agent": "Emviary (https://emviary.majjix.com)",
            "Accept": "application/geo+json",
        }
        point = self._json(
            "GET",
            "https://api.weather.gov/points/"
            f"{site.weather_location.latitude:.4f},"
            f"{site.weather_location.longitude:.4f}",
            headers=headers,
        )
        url = point["properties"]["forecastGridData"]
        # Never follow a provider-supplied URL to another host or arbitrary path.
        if not isinstance(url, str) or not re.fullmatch(
            r"https://api\.weather\.gov/gridpoints/[A-Z]{3}/[0-9]+,[0-9]+", url
        ):
            raise ValueError("Unexpected NWS grid URL")
        return nws_forecast(self._json("GET", url, headers=headers), site, local_date, now)

    def weather(self, site, local_date, now, offline, max_age, not_before):
        candidates = []
        for name, enabled in (
            ("open_meteo", site.providers.open_meteo.enabled),
            ("nws", site.providers.nws.enabled),
        ):
            if not enabled:
                continue
            key = "weather_" + name
            scope = self.scope(site, name)
            cached = self.store.snapshot(site.id, key, local_date)
            value = json_object(cached["payload"]) if cached else {}
            fetched = timestamp(value.get("fetched_at"))
            fresh = (
                fetched is not None
                and now - timedelta(minutes=max_age) < fetched <= now + timedelta(minutes=5)
                and (not_before is None or fetched >= not_before)
                and value.get("scope") == scope
            )
            try:
                if not fresh or value.get("provider") != name:
                    raise ValueError("Expired or mismatched source")
                validate_forecast(value, local_date)
                if name == "nws":
                    issued = timestamp(value.get("issued_at"))
                    if issued is None or not now - timedelta(hours=18) < issued <= now + timedelta(
                        minutes=5
                    ):
                        raise ValueError("Expired NWS issuance")
            except (ValueError, KeyError, TypeError, AttributeError):
                value = None
            if value is None and not offline:
                failure = self.store.snapshot(site.id, key + "_failure", local_date)
                failed = json_object(failure["payload"]) if failure else {}
                attempted = timestamp(failed.get("attempted_at"))
                if (
                    attempted is not None
                    and failed.get("scope") == scope
                    and now - timedelta(minutes=15) < attempted <= now
                ):
                    continue
                try:
                    value = (
                        self.forecast(site, local_date)
                        if name == "open_meteo"
                        else self.nws(site, local_date, now)
                    )
                    validate_forecast(value, local_date)
                    value.update(provider=name, scope=scope, fetched_at=now.isoformat())
                    self.store.save_snapshot(site.id, key, local_date, value, now.isoformat())
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    TypeError,
                    OSError,
                    AttributeError,
                    IndexError,
                    OverflowError,
                ) as exc:
                    log.warning("Weather source %s unavailable: %s", name, type(exc).__name__)
                    self.store.save_snapshot(
                        site.id,
                        key + "_failure",
                        local_date,
                        {
                            "scope": scope,
                            "attempted_at": now.isoformat(),
                            "error": type(exc).__name__,
                        },
                        now.isoformat(),
                    )
                    value = None
            if value is not None:
                candidates.append(value)
        if not candidates:
            return None
        value = combine_forecasts(candidates, local_date, site.timezone)
        value["scope"] = self.scope(site, "open_meteo")
        self.store.save_snapshot(site.id, "open_meteo", local_date, value, value["fetched_at"])
        return value

    def inputs(
        self,
        site,
        local_date,
        offline=False,
        *,
        now=None,
        weather_max_age_minutes=120,
        weather_not_before=None,
    ):
        now = now or datetime.now(UTC)
        results = {}
        for provider, enabled in (
            ("birdweather", site.providers.birdweather.enabled),
            ("ebird", site.providers.ebird.enabled),
        ):
            if not enabled:
                continue
            cached = self.store.snapshot(site.id, provider, local_date)
            value = json_object(cached["payload"]) if cached else {}
            received = timestamp(value.get("fetched_at", cached["received_at"])) if cached else None
            if (
                received is not None
                and received <= now + timedelta(minutes=5)
                and value.get("scope") == self.scope(site, provider)
            ):
                value["fetched_at"] = received.isoformat()
                results[provider] = value
                continue
            if not offline:
                try:
                    value = self.birds(site) if provider == "birdweather" else self.ebird(site)
                    value.update(scope=self.scope(site, provider), fetched_at=now.isoformat())
                    self.store.save_snapshot(site.id, provider, local_date, value, now.isoformat())
                    results[provider] = value
                    continue
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    TypeError,
                    OSError,
                    AttributeError,
                    IndexError,
                    OverflowError,
                ) as exc:
                    log.warning("Provider %s unavailable: %s", provider, type(exc).__name__)
            previous = self.store.snapshot(site.id, provider)
            if previous:
                received = timestamp(previous["received_at"])
                value = json_object(previous["payload"])
                if (
                    received is not None
                    and now - timedelta(hours=48) < received <= now
                    and value.get("scope") == self.scope(site, provider)
                ):
                    value["cached_fallback"] = True
                    results[provider] = value
        if site.weather_enabled:
            value = self.weather(
                site, local_date, now, offline, weather_max_age_minutes, weather_not_before
            )
            if value is not None:
                # Retain the historical manifest key for old renders/backups/devices.
                results["open_meteo"] = value
        return results
