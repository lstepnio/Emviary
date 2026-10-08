import httpx
import pytest

from emviary.providers import Providers
from emviary.render import forecast_temperatures, profile_hash, weather_label
from emviary.settings import FramePolicy


@pytest.mark.parametrize(
    "code,label", [(0, "SUNNY"), (1, "MOSTLY SUNNY"), (2, "PARTLY SUNNY"), (3, "OVERCAST")]
)
def test_daylight_sky_does_not_use_worst_overnight_clouds(code, label):
    values = dict(
        weather_code=3,
        daylight_weather_code=code,
        snowfall_sum=0,
        precipitation_probability_max=2,
        wind_speed_10m_max=14,
    )
    assert weather_label(values) == label


@pytest.mark.parametrize(
    "code,snow,label", [(95, 0, "STORMS"), (97, 0, "STORMS"), (71, 1, "SNOW"), (61, 0, "RAIN")]
)
def test_daily_precipitation_survives_sunny_daylight_summary(code, snow, label):
    values = dict(
        weather_code=code,
        daylight_weather_code=0,
        snowfall_sum=snow,
        precipitation_probability_max=80,
        wind_speed_10m_max=14,
    )
    assert weather_label(values) == label


def test_forecast_daylight_aggregation_and_date_validation(service):
    result = {
        "daily": {
            "time": ["2026-10-08"],
            "weather_code": [3],
            "temperature_2m_min": [10.1],
            "temperature_2m_max": [29.5],
            "precipitation_probability_max": [2],
            "snowfall_sum": [0],
            "wind_speed_10m_max": [14],
        },
        "daily_units": {
            "temperature_2m_min": "°C",
            "temperature_2m_max": "°C",
            "snowfall_sum": "cm",
            "wind_speed_10m_max": "km/h",
        },
        "hourly": {
            "time": [
                "2026-10-08T03:00",
                "2026-10-08T09:00",
                "2026-10-08T12:00",
                "2026-10-08T16:00",
            ],
            "weather_code": [3, 0, 0, 3],
            "is_day": [0, 1, 1, 1],
        },
    }

    def respond(request):
        assert request.url.params["hourly"] == "weather_code,is_day"
        return httpx.Response(200, json=result)

    adapter = Providers(service.store, httpx.Client(transport=httpx.MockTransport(respond)))
    site = service.settings.config.sites[0]
    values = adapter.forecast(site, "2026-10-08")["values"]
    assert values["weather_code"] == 3
    assert values["daylight_weather_code"] == 0
    assert forecast_temperatures(values) == "H 85° / L 50°F"
    result["hourly"]["time"][0] = "2026-10-09T03:00"
    with pytest.raises(ValueError, match="day"):
        adapter.forecast(site, "2026-10-08")
    result["hourly"]["time"][0] = "2026-10-08T03:00"
    result["hourly"]["is_day"] = [0, 0, 0, 0]
    with pytest.raises(ValueError, match="daylight"):
        adapter.forecast(site, "2026-10-08")


def test_temperature_default_and_cache_invalidation():
    policy = FramePolicy.model_validate({"site_id": "denver-gift"}).model_dump()
    assert policy["show_forecast_temperatures"] is True
    first = profile_hash(policy, [])
    policy["show_forecast_temperatures"] = False
    assert profile_hash(policy, []) != first
