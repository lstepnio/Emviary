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
            if "stations(first" in payload["query"]:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "stations": {
                                "nodes": [
                                    {"id": "1", "coords": {"lat": 39.7392, "lon": -104.9903}},
                                    {"id": "2", "coords": {"lat": 40.05, "lon": -104.7}},
                                ]
                            }
                        }
                    },
                )
            assert payload["variables"]["stationIds"] == ["1"]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "topSpecies": [
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
    site.bird_area = "local"
    first = adapter.inputs(site, "2026-10-08")
    assert first["birdweather"]["regional"] is True
    assert first["open_meteo"]["local_date"] == "2026-10-08"
    assert adapter.inputs(site, "2026-10-08") == first
    assert len(requests) == 3


def test_provider_outage_omits_stale_weather_and_old_birds(service):
    site = service.settings.config.sites[0]
    site.bird_area = "local"
    service.store.save_snapshot(
        site.id,
        "birdweather",
        "2026-10-07",
        {"birds": [], "scope": Providers(service.store).scope(site, "birdweather")},
    )
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


def test_ebird_presence_uses_secret_header_and_omits_personal_fields(
    service, tmp_path, monkeypatch
):
    secret = tmp_path / "ebird-key"
    secret.write_text("test-ebird-secret")
    monkeypatch.setenv("EINK_EBIRD_API_KEY_FILE", str(secret))
    calls = []

    def respond(request):
        calls.append(request)
        assert request.headers["X-eBirdApiToken"] == "test-ebird-secret"
        assert "test-ebird-secret" not in str(request.url)
        assert request.url.params["dist"] == "25"
        assert request.url.params["back"] == "7"
        assert request.url.params["maxResults"] == "100"
        assert request.url.params["includeProvisional"] == "false"
        return httpx.Response(
            200,
            json=[
                {
                    "sciName": "Pica hudsonia",
                    "comName": "Black-billed Magpie",
                    "speciesCode": "bkbmag1",
                    "obsDt": "2026-10-07 10:15",
                    "howMany": 99,
                    "lat": 39.7,
                    "lng": -105.0,
                    "locName": "Private backyard",
                    "subId": "S123",
                }
            ]
            * 2,
        )

    site = service.settings.config.sites[0].model_copy(deep=True)
    site.bird_area = "local"
    site.providers.birdweather.enabled = False
    site.providers.open_meteo.enabled = False
    site.providers.ebird.enabled = True
    adapter = Providers(service.store, httpx.Client(transport=httpx.MockTransport(respond)))
    first = adapter.inputs(site, "2026-10-08")
    assert len(first["ebird"]["birds"]) == 1
    assert first["ebird"]["evidence_type"] == "reported_presence"
    serialized = json.dumps(first)
    assert all(
        value not in serialized
        for value in (
            "test-ebird-secret",
            "Private backyard",
            "subId",
            "howMany",
            "locName",
        )
    )
    assert adapter.inputs(site, "2026-10-08") == first
    assert len(calls) == 1


def test_missing_ebird_secret_does_not_block_offline_art(service, tmp_path, monkeypatch):
    monkeypatch.setenv("EINK_EBIRD_API_KEY_FILE", str(tmp_path / "missing"))
    site = service.settings.config.sites[0].model_copy(deep=True)
    site.bird_area = "local"
    site.providers.birdweather.enabled = False
    site.providers.open_meteo.enabled = False
    site.providers.ebird.enabled = True
    assert Providers(service.store).inputs(site, "2026-10-08") == {}


def test_colorado_queries_state_and_accepts_distant_in_state_birds(service, tmp_path, monkeypatch):
    secret = tmp_path / "key"
    secret.write_text("test-secret")
    monkeypatch.setenv("EINK_EBIRD_API_KEY_FILE", str(secret))
    site = service.settings.config.sites[0].model_copy(deep=True)
    site.bird_area = "colorado"
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            if "stations(first" in payload["query"]:
                assert payload["variables"]["sw"]["lat"] == 37
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "stations": {
                                "nodes": [
                                    {"id": "far", "coords": {"lat": 38.5, "lon": -108.5}},
                                    {"id": "outside", "coords": {"lat": 42, "lon": -105}},
                                ]
                            }
                        }
                    },
                )
            assert payload["variables"]["stationIds"] == ["far"]
            return httpx.Response(200, json={"data": {"topSpecies": []}})
        assert request.url.path == "/v2/data/obs/US-CO/recent"
        assert "dist" not in request.url.params
        return httpx.Response(
            200,
            json=[
                {"sciName": "Pica hudsonia", "lat": 38.5, "lng": -108.5},
                {"sciName": "Outside", "lat": 42, "lng": -105},
            ],
        )

    adapter = Providers(service.store, httpx.Client(transport=httpx.MockTransport(respond)))
    assert len(adapter.ebird(site)["birds"]) == 1
    assert adapter.birds(site)["station_count"] == 1
    local = site.model_copy(update={"bird_area": "local"})
    assert adapter.scope(local, "ebird") != adapter.scope(site, "ebird")
    assert site.weather_location == local.weather_location
