"""Normalize independent forecasts without averaging condition codes or stale days."""

import math
import re
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from .render import weather_label
from .status_data import timestamp

UNITS = {
    "temperature_2m_min": "°C",
    "temperature_2m_max": "°C",
    "snowfall_sum": "cm",
    "wind_speed_10m_max": "km/h",
}
CODES = {
    0,
    1,
    2,
    3,
    45,
    48,
    51,
    53,
    55,
    56,
    57,
    61,
    63,
    65,
    66,
    67,
    71,
    73,
    75,
    77,
    80,
    81,
    82,
    85,
    86,
    95,
    96,
    97,
    99,
}


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid forecast number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Forecast number outside supported range")
    return value


def validate_forecast(value, local_date):
    if not isinstance(value, dict) or value.get("local_date") != local_date:
        raise ValueError("Forecast date mismatch")
    if "units" in value and any(value["units"].get(k) != v for k, v in UNITS.items()):
        raise ValueError("Unexpected normalized forecast units")
    values = value["values"]
    for key in ("weather_code", "daylight_weather_code"):
        if key in values and number(values[key], 0, 99) not in CODES:
            raise ValueError("Unknown forecast condition")
    if "weather_code" not in values:
        raise ValueError("Missing forecast condition")
    low = number(values["temperature_2m_min"], -90, 65)
    high = number(values["temperature_2m_max"], -90, 65)
    if low > high:
        raise ValueError("Forecast low exceeds high")
    number(values["precipitation_probability_max"], 0, 100)
    number(values["snowfall_sum"], 0, 300)
    number(values["wind_speed_10m_max"], 0, 450)
    return value


def interval(value):
    start, duration = value.split("/", 1)
    start = timestamp(start)
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", duration)
    if start is None or match is None:
        raise ValueError("Invalid forecast interval")
    days, hours, minutes, seconds = [int(n or 0) for n in match.groups()]
    delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if not timedelta(0) < delta <= timedelta(days=16):
        raise ValueError("Invalid forecast duration")
    return start, start + delta


def nws_forecast(result, site, local_date, now):
    properties = result["properties"]
    issued = timestamp(properties.get("updateTime"))
    # NWS grid products are issued less frequently than our fetches. Record both
    # clocks; downloading an old grid again never makes its issuance fresh.
    if issued is None or not now - timedelta(hours=18) < issued <= now + timedelta(minutes=5):
        raise ValueError("NWS grid issuance is stale")
    zone = ZoneInfo(site.timezone)
    day = datetime.fromisoformat(local_date).date()
    start = datetime.combine(day, time(), zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(UTC)

    def at(hour):
        return datetime.combine(day, time(hour), zone).astimezone(UTC)

    def samples(key, unit=None):
        field = properties[key]
        if unit is not None and field.get("uom") != unit:
            raise ValueError("Unexpected NWS unit")
        entries = field["values"]
        if not isinstance(entries, list) or len(entries) > 1000:
            raise ValueError("Invalid NWS series")
        for entry in entries:
            first, last = interval(entry["validTime"])
            overlap = (min(last, end) - max(first, start)).total_seconds()
            if overlap > 0:
                yield first, last, overlap, entry["value"]

    def daily_temperature(key, hour):
        matches = [
            number(v, -90, 65) for a, b, _, v in samples(key, "wmoUnit:degC") if a <= at(hour) < b
        ]
        if len(matches) != 1:
            raise ValueError("NWS daily temperature coverage is incomplete")
        return matches[0]

    sky = Counter()
    for first, last, _, value in samples("skyCover", "wmoUnit:percent"):
        cloud = number(value, 0, 100)
        seconds = (min(last, at(18)) - max(first, at(8))).total_seconds()
        if seconds > 0:
            code = 0 if cloud < 12.5 else 1 if cloud < 37.5 else 2 if cloud < 75 else 3
            sky[code] += seconds
    if sum(sky.values()) < 8 * 3600:
        raise ValueError("NWS daylight coverage is incomplete")
    sky_code = max(sky, key=lambda code: (sky[code], code))
    probabilities = [
        number(v, 0, 100) for _, _, _, v in samples("probabilityOfPrecipitation", "wmoUnit:percent")
    ]
    winds = [number(v, 0, 450) for _, _, _, v in samples("windSpeed", "wmoUnit:km_h-1")]
    snow = [
        number(v, 0, 3000) * overlap / (b - a).total_seconds() / 10
        for a, b, overlap, v in samples("snowfallAmount", "wmoUnit:mm")
    ]
    if not probabilities or not winds or not snow:
        raise ValueError("NWS daily forecast is incomplete")
    conditions = set()
    for _, _, _, entries in samples("weather"):
        if not isinstance(entries, list):
            raise ValueError("Invalid NWS conditions")
        conditions.update(entry["weather"] for entry in entries if entry.get("weather"))
    code = sky_code
    if "thunderstorms" in conditions:
        code = 95
    elif conditions & {"snow", "snow_showers", "blowing_snow", "ice_pellets"}:
        code = 71
    elif conditions & {"freezing_rain", "freezing_drizzle"}:
        code = 66
    elif conditions & {"rain", "rain_showers", "drizzle"}:
        code = 61
    elif conditions & {"fog", "freezing_fog"}:
        code = 45
        sky_code = 45
    return validate_forecast(
        {
            "provider": "nws",
            "local_date": local_date,
            "timezone": site.timezone,
            "issued_at": issued.isoformat(),
            "units": UNITS,
            "values": {
                "weather_code": code,
                "daylight_weather_code": sky_code,
                "temperature_2m_max": daily_temperature("maxTemperature", 12),
                "temperature_2m_min": daily_temperature("minTemperature", 6),
                "precipitation_probability_max": max(probabilities),
                "wind_speed_10m_max": max(winds),
                "snowfall_sum": sum(snow),
            },
        },
        local_date,
    )


def combine_forecasts(candidates, local_date, timezone):
    """Use agreement for temperatures; conditions stay internally consistent.

    With two sources there is no statistical way to identify the wrong outlier.
    Prefer the local NWS product when conditions or temperatures disagree, and
    expose that decision instead of presenting a blended result as consensus.
    """
    candidates = [validate_forecast(c, local_date) for c in candidates]
    labels = Counter(weather_label(c["values"]) for c in candidates)
    selected = max(
        candidates, key=lambda c: (labels[weather_label(c["values"])], c["provider"] == "nws")
    )
    values = selected["values"].copy()
    spread = max(
        max(c["values"][key] for c in candidates) - min(c["values"][key] for c in candidates)
        for key in ("temperature_2m_min", "temperature_2m_max")
    )
    if spread <= 6:
        for key in ("temperature_2m_min", "temperature_2m_max"):
            values[key] = median(c["values"][key] for c in candidates)
    return {
        "provider": "weather_consensus",
        "local_date": local_date,
        "timezone": timezone,
        "values": values,
        "units": UNITS,
        "sources": [
            {k: c[k] for k in ("provider", "fetched_at", "issued_at") if k in c} for c in candidates
        ],
        "selected_source": selected["provider"],
        "agreement": "single_source"
        if len(candidates) == 1
        else "disagreement"
        if spread > 6 or len(labels) > 1
        else "agreement",
        "temperature_spread_c": round(spread, 1),
        # Freshness is bounded by the oldest contributor, never the newest fetch.
        "fetched_at": min(timestamp(c["fetched_at"]) for c in candidates).isoformat(),
    }
