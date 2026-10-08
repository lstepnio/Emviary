import json
from datetime import UTC, datetime, timedelta

import httpx

from einkartifact.providers import Providers


def test_real_adapter_shapes_are_bounded_and_cached_by_site(service):
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["variables"]["period"] == {
                "count": 24,
                "unit": "hours",
                "timezone": "America/Denver",
            }
            return httpx.Response(
                200,
                json={
                    "data": {
                        "topBirdnetSpecies": [
                            {
                                "count": 8,
                                "species": {
                                    "id": "565",
                                    "commonName": "Black-billed Magpie",
                                    "scientificName": "Pica hudsonia",
                                },
                            }
                        ]
                    }
                },
            )
        assert request.url.params["start_date"] == "2026-10-08"
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-10-08"],
                    "weather_code": [2],
                    "temperature_2m_min": [4],
                    "temperature_2m_max": [20],
                    "precipitation_probability_max": [10],
                    "snowfall_sum": [0],
                    "wind_speed_10m_max": [15],
                },
                "daily_units": {
                    "temperature_2m_min": "°C",
                    "temperature_2m_max": "°C",
                    "snowfall_sum": "cm",
                    "wind_speed_10m_max": "km/h",
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    adapter = Providers(service.store, client)
    site = service.settings.config.sites[0]
    first = adapter.inputs(site, "2026-10-08")
    assert first["birdweather"]["regional"] is True
    assert first["open_meteo"]["local_date"] == "2026-10-08"
    assert adapter.inputs(site, "2026-10-08") == first
    assert len(requests) == 2


def test_provider_outage_omits_stale_weather_and_old_birds(service):
    site = service.settings.config.sites[0]
    service.store.save_snapshot(site.id, "birdweather", "2026-10-07", {"birds": []})
    service.store.save_snapshot(site.id, "open_meteo", "2026-10-07", {"local_date": "2026-10-07"})

    def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    adapter = Providers(service.store, httpx.Client(transport=httpx.MockTransport(unavailable)))
    first = adapter.inputs(site, "2026-10-08")
    assert "open_meteo" not in first
    assert first["birdweather"]["cached_fallback"] is True
    with service.store.connect() as db:
        db.execute(
            "UPDATE provider_snapshots SET received_at=? WHERE provider='birdweather'",
            ((datetime.now(UTC) - timedelta(days=3)).isoformat(),),
        )
    assert adapter.inputs(site, "2026-10-08") == {}


def test_graphql_error_and_wrong_forecast_date_use_catalog_fallback(service):
    def invalid(request):
        if request.method == "POST":
            return httpx.Response(200, json={"errors": [{"message": "unavailable"}]})
        return httpx.Response(200, json={"daily": {"time": ["2026-10-07"]}})

    adapter = Providers(service.store, httpx.Client(transport=httpx.MockTransport(invalid)))
    assert adapter.inputs(service.settings.config.sites[0], "2026-10-08") == {}
