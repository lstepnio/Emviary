import copy
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from emviary.providers import Providers
from emviary.weather import combine_forecasts, nws_forecast

NOW = datetime(2026, 10, 20, 8, tzinfo=UTC)
DAY = "2026-10-20"


def forecast(provider="open_meteo", low=8, high=22, code=0):
    return {
        "provider": provider,
        "local_date": DAY,
        "fetched_at": NOW.isoformat(),
        "values": {
            "temperature_2m_min": low,
            "temperature_2m_max": high,
            "weather_code": code,
            "daylight_weather_code": code,
            "precipitation_probability_max": 0,
            "snowfall_sum": 0,
            "wind_speed_10m_max": 10,
        },
    }


def grid():
    def series(value, unit, start="2026-10-20T00:00:00-06:00/P1D"):
        return {"uom": unit, "values": [{"validTime": start, "value": value}]}

    return {
        "properties": {
            "updateTime": (NOW - timedelta(hours=6)).isoformat(),
            "maxTemperature": series(22, "wmoUnit:degC", "2026-10-20T08:00:00-06:00/PT13H"),
            "minTemperature": series(8, "wmoUnit:degC", "2026-10-19T20:00:00-06:00/PT14H"),
            "skyCover": series(30, "wmoUnit:percent"),
            "windSpeed": series(14, "wmoUnit:km_h-1"),
            "probabilityOfPrecipitation": series(10, "wmoUnit:percent"),
            "snowfallAmount": series(0, "wmoUnit:mm"),
            "weather": series([{"weather": None}], None),
        }
    }


def test_nws_intervals_units_predawn_low_and_daytime_high(service):
    site = service.settings.config.sites[0]
    result = nws_forecast(grid(), site, DAY, NOW)
    assert result["values"]["temperature_2m_min"] == 8
    assert result["values"]["temperature_2m_max"] == 22
    assert result["values"]["daylight_weather_code"] == 1
    assert result["issued_at"] == (NOW - timedelta(hours=6)).isoformat()
    with pytest.raises(ValueError):
        nws_forecast(grid(), site, "2026-10-21", NOW)


@pytest.mark.parametrize("fault", ["old", "future", "units", "null", "missing", "overlap"])
def test_nws_rejects_invalid_and_stale_data(service, fault):
    result = grid()
    p = result["properties"]
    if fault == "old":
        p["updateTime"] = (NOW - timedelta(hours=19)).isoformat()
    elif fault == "future":
        p["updateTime"] = (NOW + timedelta(hours=1)).isoformat()
    elif fault == "units":
        p["windSpeed"]["uom"] = "mph"
    elif fault == "null":
        p["minTemperature"]["values"][0]["value"] = None
    elif fault == "missing":
        p["skyCover"]["values"] = []
    else:
        p["maxTemperature"]["values"] *= 2
    with pytest.raises(ValueError):
        nws_forecast(result, service.settings.config.sites[0], DAY, NOW)


def test_consensus_does_not_average_categories_or_large_temperature_disagreement():
    a, b = forecast(), forecast("nws", 10, 24, 3)
    result = combine_forecasts([a, b], DAY, "America/Denver")
    assert result["values"]["temperature_2m_min"] == 9
    assert result["values"]["temperature_2m_max"] == 23
    assert result["values"]["weather_code"] == 3
    assert result["agreement"] == "disagreement"
    a["values"]["temperature_2m_max"] = 50
    result = combine_forecasts([a, b], DAY, "America/Denver")
    assert result["values"]["temperature_2m_max"] == 24
    assert result["temperature_spread_c"] == 26
    assert result["selected_source"] == "nws"
    assert combine_forecasts([a], DAY, "America/Denver")["agreement"] == "single_source"


def adapter(service, monkeypatch):
    site = service.settings.config.sites[0]
    site.providers.birdweather.enabled = False
    site.providers.nws.enabled = True
    provider = Providers(service.store)
    monkeypatch.setattr(provider, "forecast", lambda *a: forecast())
    monkeypatch.setattr(
        provider, "nws", lambda *a: {**forecast("nws"), "issued_at": NOW.isoformat()}
    )
    return provider, site


@pytest.mark.parametrize("failed", ["open_meteo", "nws", "both"])
def test_independent_outages_and_recovery_have_bounded_retry(service, monkeypatch, failed):
    provider, site = adapter(service, monkeypatch)
    calls = []

    def unavailable(*args):
        calls.append(1)
        raise httpx.ReadTimeout("provider failure")

    if failed in ("open_meteo", "both"):
        monkeypatch.setattr(provider, "forecast", unavailable)
    if failed in ("nws", "both"):
        monkeypatch.setattr(provider, "nws", unavailable)
    first = provider.inputs(site, DAY, now=NOW)
    assert ("open_meteo" in first) == (failed != "both")
    if failed != "both":
        assert len(first["open_meteo"]["sources"]) == 1
    count = len(calls)
    provider.inputs(site, DAY, now=NOW + timedelta(minutes=1))
    assert len(calls) == count
    monkeypatch.setattr(provider, "forecast", lambda *a: forecast())
    monkeypatch.setattr(
        provider, "nws", lambda *a: {**forecast("nws"), "issued_at": NOW.isoformat()}
    )
    recovered = provider.inputs(site, DAY, now=NOW + timedelta(minutes=16))["open_meteo"]
    assert len(recovered["sources"]) == 2


@pytest.mark.parametrize(
    "bad", ["{", "[]", "null", '{"fetched_at":42}', '{"fetched_at":"2026-10-20T08:00:00"}']
)
def test_corrupt_cached_sources_are_refetched_without_aborting(service, monkeypatch, bad):
    provider, site = adapter(service, monkeypatch)
    provider.inputs(site, DAY, now=NOW)
    with service.store.connect() as db:
        db.execute("UPDATE provider_snapshots SET payload=?", (bad,))
    assert len(provider.inputs(site, DAY, now=NOW)["open_meteo"]["sources"]) == 2


def test_strict_daily_fetch_window_excludes_early_cache_and_other_days(service, monkeypatch):
    provider, site = adapter(service, monkeypatch)
    early = provider.inputs(site, DAY, now=NOW)["open_meteo"]
    deadline = NOW + timedelta(minutes=45)
    fresh = provider.inputs(site, DAY, now=deadline, weather_not_before=deadline)["open_meteo"]
    assert early["fetched_at"] != fresh["fetched_at"]
    assert fresh["fetched_at"] == deadline.isoformat()
    assert provider.inputs(site, "2026-10-21", now=deadline, offline=True) == {}


def test_bad_provider_shapes_cannot_abort_other_sources(service, monkeypatch):
    provider, site = adapter(service, monkeypatch)
    monkeypatch.setattr(provider, "forecast", lambda *a: [])
    assert provider.inputs(site, DAY, now=NOW)["open_meteo"]["selected_source"] == "nws"


def test_nws_refuses_untrusted_grid_url(service):
    site = service.settings.config.sites[0]
    provider = Providers(
        service.store,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "properties": {
                            "forecastGridData": "https://internal.invalid/gridpoints/BOU/1,2"
                        }
                    },
                )
            )
        ),
    )
    with pytest.raises(ValueError, match="URL"):
        provider.nws(site, DAY, NOW)


def test_nws_dst_day_uses_local_boundaries(service):
    site = service.settings.config.sites[0]
    result = grid()
    for field in result["properties"].values():
        if isinstance(field, dict):
            for entry in field["values"]:
                entry["validTime"] = "2026-11-01T00:00:00-06:00/PT25H"
    result["properties"]["updateTime"] = "2026-11-01T06:00:00+00:00"
    actual = nws_forecast(result, site, "2026-11-01", datetime(2026, 11, 1, 8, tzinfo=UTC))
    assert actual["local_date"] == "2026-11-01"
    assert actual["values"]["temperature_2m_max"] == 22


def test_independent_cache_oldest_contributor_controls_freshness(service, monkeypatch):
    provider, site = adapter(service, monkeypatch)
    provider.inputs(site, DAY, now=NOW)
    source = json.loads(service.store.snapshot(site.id, "weather_nws", DAY)["payload"])
    source["fetched_at"] = (NOW - timedelta(minutes=30)).isoformat()
    service.store.save_snapshot(site.id, "weather_nws", DAY, copy.deepcopy(source))
    result = provider.inputs(site, DAY, now=NOW)["open_meteo"]
    assert result["fetched_at"] == source["fetched_at"]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_http_weather_failure_cannot_suppress_other_source(service, monkeypatch, status):
    provider, site = adapter(service, monkeypatch)

    def failure(*args):
        request = httpx.Request("GET", "https://api.open-meteo.com/v1/forecast")
        response = httpx.Response(status, request=request)
        response.raise_for_status()

    monkeypatch.setattr(provider, "forecast", failure)
    result = provider.inputs(site, DAY, now=NOW)["open_meteo"]
    assert result["selected_source"] == "nws"
    assert result["agreement"] == "single_source"
