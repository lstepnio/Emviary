import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.providers import Providers
from emviary.service import Service
from emviary.settings import FramePolicy


def install_weather(service, monkeypatch):
    clock = [datetime(2026, 10, 8, 7, tzinfo=UTC)]  # 01:00 Denver
    service.clock = lambda: clock[0]
    adapter = Providers(service.store)
    calls = []

    def forecast(site, local_date):
        calls.append((local_date, clock[0]))
        return {
            "provider": "open_meteo",
            "local_date": local_date,
            "values": {
                "weather_code": 0,
                "daylight_weather_code": 0,
                "temperature_2m_max": 20 + len(calls),
                "temperature_2m_min": 5,
                "precipitation_probability_max": 0,
                "snowfall_sum": 0,
                "wind_speed_10m_max": 10,
            },
        }

    monkeypatch.setattr(adapter, "forecast", forecast)
    monkeypatch.setattr(adapter, "birds", lambda site: {"birds": []})
    monkeypatch.setattr(adapter, "ebird", lambda site: {"birds": []})
    service.providers = adapter
    return clock, calls


def plan(image):
    return json.loads(image["manifest"])


def test_early_navigation_does_not_satisfy_daily_forecast(service, frame, monkeypatch):
    clock, calls = install_weather(service, monkeypatch)
    early = service.prepare(frame[0])
    service.prepare_due(clock[0])
    assert service.store.slot_image(frame[0], "scheduled") is None
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due(clock[0])
    daily = service.store.slot_image(frame[0], "scheduled")
    assert daily["id"] != early["id"]
    assert plan(daily)["inputs"]["open_meteo"]["fetched_at"] == clock[0].isoformat()
    assert len(calls) == 2  # Even though the 01:00 snapshot is less than two hours old.
    assert service.store.slot_image(frame[0], "navigation")["id"] == daily["id"]
    service.prepare_due(clock[0] + timedelta(minutes=1))
    assert len(calls) == 2
    selected, retain = service.select_image(service.store.frame(frame[0]), "latest", "")
    assert selected["id"] == daily["id"] and not retain


def test_delivery_refills_next_without_replacing_daily_or_mirror(service, frame, monkeypatch):
    clock, calls = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    daily = service.store.slot_image(frame[0], "scheduled")
    tag = '"' + daily["body_hash"] + '-c1"'
    service.image_delivered(frame[0], daily["id"], 80, "test", "", tag)
    next_image = service.store.slot_image(frame[0], "navigation")
    assert next_image["id"] > daily["id"]
    assert service.store.slot_image(frame[0], "scheduled")["id"] == daily["id"]
    assert service.delivered_image(service.store.frame(frame[0]))["body_hash"] == daily["body_hash"]
    assert len(calls) == 1
    selected, _ = service.select_image(service.store.frame(frame[0]), "next", tag)
    assert selected["id"] == next_image["id"]
    selected, _ = service.select_image(service.store.frame(frame[0]), "latest", tag)
    assert selected["id"] == daily["id"]


def test_weather_expiry_refreshes_unconsumed_birds_without_rotating_them(
    service, frame, monkeypatch
):
    clock, calls = install_weather(service, monkeypatch)
    initial = service.prepare(frame[0])
    clock[0] += timedelta(hours=2)
    service.request_navigation_refresh(service.store.frame(frame[0]))
    service.refill_pending()
    fresh = service.store.slot_image(frame[0], "navigation")
    assert fresh["id"] > initial["id"]
    assert plan(fresh)["artworks"] == plan(initial)["artworks"]
    assert plan(fresh)["layout"] == plan(initial)["layout"]
    assert plan(fresh)["inputs"]["open_meteo"]["fetched_at"] == clock[0].isoformat()
    assert len(calls) == 2


def test_midnight_changes_target_day_without_network_on_fetch(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 9, 5, 59, tzinfo=UTC)
    old = service.prepare(frame[0])  # Still October 8 in Denver.
    clock[0] += timedelta(minutes=1)
    selected, retain = service.select_image(
        service.store.frame(frame[0]), "latest", '"' + old["body_hash"] + '-c1"'
    )
    assert retain and selected["id"] == old["id"]
    assert service.select_image(service.store.frame(frame[0]), "next", "") == (None, False)
    service.prepare_due()
    current = service.store.slot_image(frame[0], "navigation")
    assert current["local_date"] == "2026-10-09"
    assert service.store.slot_image(frame[0], "scheduled") is None


def test_stale_api_retains_panel_and_queues_work_without_blocking(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    old = service.prepare(frame[0])
    clock[0] += timedelta(hours=2)
    monkeypatch.setattr(service, "image_delivered", lambda *args: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("No provider or renderer is allowed on the request path")

    monkeypatch.setattr(service.providers, "inputs", forbidden)
    monkeypatch.setattr(service, "converter", forbidden)
    client = TestClient(create_app(service, schedule=False))
    headers = {"Authorization": "Bearer " + frame[1], "X-Firmware-Version": "v0.7.6"}
    response = client.get(
        "/v1/image", headers={**headers, "If-None-Match": '"' + old["body_hash"] + '-c1"'}
    )
    assert response.status_code == 304 and not response.content
    assert response.headers["x-image-readiness"].startswith("retained")
    assert service.store.pending_refills(frame[0])
    response = client.get("/v1/image", headers=headers)
    assert response.status_code == 503 and response.headers["retry-after"] == "300"


def test_weather_outage_omits_expired_forecast_and_recovers(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    old = service.prepare(frame[0])
    clock[0] += timedelta(hours=2)
    real_forecast = service.providers.forecast
    monkeypatch.setattr(
        service.providers, "forecast", lambda *args: (_ for _ in ()).throw(ValueError())
    )
    service.request_navigation_refresh(service.store.frame(frame[0]))
    service.refill_pending()
    fallback = service.store.slot_image(frame[0], "navigation")
    assert "open_meteo" not in plan(fallback)["inputs"]
    assert plan(fallback)["artworks"] == plan(old)["artworks"]
    selected, retain = service.select_image(service.store.frame(frame[0]), "next", "")
    assert selected["id"] == fallback["id"] and not retain
    monkeypatch.setattr(service.providers, "forecast", real_forecast)
    clock[0] += timedelta(hours=2)
    service.prepare_due()
    assert "open_meteo" in plan(service.store.slot_image(frame[0], "navigation"))["inputs"]


def test_daily_and_initial_failures_are_bounded_and_persist(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    attempts = []

    def fail(*args):
        attempts.append(args[0].name)
        raise TimeoutError()

    monkeypatch.setattr(service, "converter", fail)
    for minute in (0, 1, 15, 16, 30, 31, 45):
        service.prepare_due(clock[0] + timedelta(minutes=minute))
    # Independent bounded retry budgets: 3 scheduled + 3 navigation/bootstrap.
    # Each job has one optional neutral conversion and one main conversion;
    # failed optional conversion must not introduce additional job attempts.
    assert attempts.count("master.png") == 6
    assert attempts.count("neutral.png") == 6
    # Preview retries are independent: three today, then one for tomorrow
    # once the clock reaches today's wake. None publish a deliverable image.
    assert attempts.count("composition.png") == 4
    assert len(attempts) == 16
    assert service.store.slot_state(frame[0], "scheduled")["attempts"] == 3
    restarted = Service(service.settings, service.providers, fail, clock=service.clock)
    restarted.prepare_due(clock[0] + timedelta(minutes=50))
    assert attempts.count("master.png") == 6
    assert attempts.count("neutral.png") == 6
    # Preview retries are independent: three today, then one for tomorrow
    # once the clock reaches today's wake. None publish a deliverable image.
    assert attempts.count("composition.png") == 4
    assert len(attempts) == 16
    assert service.store.pending_refills(frame[0])[0]["attempts"] == 3


def test_cached_daily_job_republishes_slot_after_interruption(service, frame, monkeypatch):
    clock, calls = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    original = service.store.slot_image(frame[0], "scheduled")
    with service.store.connect() as db:
        db.execute("UPDATE prepared_slots SET image_id=NULL WHERE purpose='scheduled'")
    service.prepare_due(clock[0] + timedelta(minutes=15))
    assert service.store.slot_image(frame[0], "scheduled")["id"] == original["id"]
    assert len(calls) == 1


def test_weather_off_has_no_age_expiry_but_still_has_date_expiry(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    service.store.set_policy(frame[0], FramePolicy(weather_cues=False))
    initial = service.prepare(frame[0])
    clock[0] += timedelta(hours=10)
    assert service.image_usable(initial, service.store.frame(frame[0]))
    clock[0] += timedelta(days=1)
    assert not service.image_usable(initial, service.store.frame(frame[0]))


def test_freshness_policy_is_bounded():
    assert FramePolicy().weather_max_age_minutes == 120
    for invalid in (0, 14, 1441):
        with pytest.raises(ValueError):
            FramePolicy(weather_max_age_minutes=invalid)


def test_expired_failed_plan_gets_new_weather_before_retry(service, frame, monkeypatch):
    clock, calls = install_weather(service, monkeypatch)
    converter = service.converter
    monkeypatch.setattr(service, "converter", lambda *a: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(TimeoutError):
        service.prepare(frame[0])
    clock[0] += timedelta(hours=2)
    monkeypatch.setattr(service, "converter", converter)
    recovered = service.prepare(frame[0])
    assert plan(recovered)["inputs"]["open_meteo"]["fetched_at"] == clock[0].isoformat()
    assert len(calls) == 2


def test_previous_keeps_original_bytes_even_when_forecast_is_old(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    first = service.prepare(frame[0])
    clock[0] += timedelta(hours=1)
    second = service.prepare(frame[0], force=True)
    clock[0] += timedelta(hours=4)
    previous, retain = service.select_image(
        service.store.frame(frame[0]), "previous", '"' + second["body_hash"] + '-c1"'
    )
    assert previous["id"] == first["id"] and not retain
    assert not service.image_usable(previous, service.store.frame(frame[0]))


def test_preparation_time_is_clamped_to_fresh_window_before_wake(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    site = service.settings.config.sites[0]
    site.prepare_local_time = "23:30"
    service.prepare(frame[0])
    service.prepare_due()
    assert service.store.slot_image(frame[0], "scheduled") is None
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    assert service.store.slot_image(frame[0], "scheduled")["local_date"] == "2026-10-08"


@pytest.mark.parametrize(
    "now", [datetime(2026, 11, 1, 9, 30, tzinfo=UTC), datetime(2026, 3, 8, 8, 30, tzinfo=UTC)]
)
def test_schedule_obeys_denver_clock_across_dst(service, frame, monkeypatch, now):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = now
    service.prepare_due()
    daily = service.store.slot_image(frame[0], "scheduled")
    assert daily and daily["local_date"] == now.date().isoformat()
    assert service.image_usable(daily, service.store.frame(frame[0]))


def test_config_change_invalidates_both_slots_and_refreshes_independently(
    service, frame, monkeypatch
):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    old = service.store.slot_image(frame[0], "scheduled")
    policy = FramePolicy.model_validate_json(service.store.frame(frame[0])["policy"])
    policy.show_weather_icon = False
    service.store.set_policy(frame[0], policy)
    assert not service.image_usable(old, service.store.frame(frame[0]))
    service.prepare_due(clock[0] + timedelta(minutes=1))
    fresh = service.store.slot_image(frame[0], "scheduled")
    assert fresh["id"] != old["id"]
    assert service.image_usable(fresh, service.store.frame(frame[0]))


def test_owner_has_separate_previews_and_freshness_setting(service, frame, tmp_path, monkeypatch):
    from test_owner import sign_in

    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    home = client.get("/manage").text
    assert "Daily refresh" in home and "Next button" in home and "Forecast updated" in home
    assert client.get("/manage/frames/test-frame/prepared/scheduled").status_code == 200
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.get("/manage/frames/test-frame/prepared/scheduled").status_code == 401
    assert 'name="weather_max_age"' in client.get("/manage/appearance").text
    data = {
        "csrf": csrf,
        "wake": "03:15",
        "max_birds": "3",
        "preset": "soft",
        "dither": "stucki",
        "weather": "on",
        "weather_max_age": "60",
    }
    assert client.post("/manage/frames/test-frame/settings", data=data).status_code == 200
    assert json.loads(service.store.frame(frame[0])["policy"])["weather_max_age_minutes"] == 60
    assert (
        client.post(
            "/manage/frames/test-frame/settings", data={**data, "weather_max_age": "10"}
        ).status_code
        == 400
    )


def test_midnight_wake_prepares_tomorrow_without_serving_it_early(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    service.store.set_policy(
        frame[0], FramePolicy(wake_local_time="00:15", firmware_rotate_cron=["15 0 *"])
    )
    service.settings.config.sites[0].prepare_local_time = "23:30"
    clock[0] = datetime(2026, 10, 9, 5, 30, tzinfo=UTC)  # 23:30 Denver, October 8
    service.prepare_due()
    tomorrow = service.store.slot_image(frame[0], "scheduled")
    assert tomorrow["local_date"] == "2026-10-09"
    selected, _ = service.select_image(service.store.frame(frame[0]), "latest", "")
    assert selected["local_date"] == "2026-10-08"
    clock[0] += timedelta(minutes=45)
    selected, retain = service.select_image(service.store.frame(frame[0]), "latest", "")
    assert selected["id"] == tomorrow["id"] and not retain


def test_overview_advances_to_next_wake_without_reusing_delivered_daily(
    service, frame, monkeypatch, tmp_path
):
    from test_owner import sign_in

    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    daily = service.store.slot_image(frame[0], "scheduled")
    client, _ = sign_in(service, tmp_path, monkeypatch)
    assert service.next_daily_refresh(service.store.frame(frame[0]))["image"]["id"] == daily["id"]
    assert client.get("/manage/frames/test-frame/prepared/scheduled").status_code == 200
    clock[0] = datetime(2026, 10, 8, 9, 15, tzinfo=UTC)  # Exactly at the saved wake.
    upcoming = service.next_daily_refresh(service.store.frame(frame[0]))
    assert upcoming["wake_at"] == datetime(2026, 10, 9, 9, 15, tzinfo=UTC)
    assert upcoming["prepare_at"] == datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
    assert upcoming["image"] is None and upcoming["status"] == "waiting"
    home = client.get("/manage").text
    daily_card = home.split("<h3>Daily refresh</h3>")[1].split("<h3>Next button</h3>")[0]
    assert "Oct 09, 03:15 AM" in daily_card
    assert "Oct 09, 02:30 AM" in daily_card
    assert "/prepared/scheduled" not in daily_card
    assert "Waiting for fresh preparation" not in daily_card
    assert client.get("/manage/frames/test-frame/prepared/scheduled").status_code == 404
    # Nothing changes in the worker's completed daily slot or the confirmed picture.
    assert service.store.slot_image(frame[0], "scheduled")["id"] == daily["id"]
    clock[0] = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
    service.prepare_due()
    upcoming = service.next_daily_refresh(service.store.frame(frame[0]))
    assert upcoming["status"] == "ready"
    assert upcoming["image"]["local_date"] == "2026-10-09"
    assert client.get("/manage/frames/test-frame/prepared/scheduled").status_code == 200


def test_next_daily_preview_evaluates_midnight_forecast_at_target_wake(
    service, frame, monkeypatch, tmp_path
):
    from test_owner import sign_in

    clock, _ = install_weather(service, monkeypatch)
    service.store.set_policy(
        frame[0], FramePolicy(wake_local_time="00:15", firmware_rotate_cron=["15 0 *"])
    )
    service.settings.config.sites[0].prepare_local_time = "23:30"
    clock[0] = datetime(2026, 10, 9, 5, 30, tzinfo=UTC)
    service.prepare_due()
    upcoming = service.next_daily_refresh(service.store.frame(frame[0]))
    assert upcoming["status"] == "ready"
    assert upcoming["image"]["local_date"] == "2026-10-09"
    client, _ = sign_in(service, tmp_path, monkeypatch)
    daily_card = (
        client.get("/manage")
        .text.split("<h3>Daily refresh</h3>")[1]
        .split("<h3>Next button</h3>")[0]
    )
    assert "Ready" in daily_card and "Waiting for fresh preparation" not in daily_card


def test_next_daily_preview_distinguishes_expected_wait_from_failed_preparation(
    service, frame, monkeypatch
):
    clock, _ = install_weather(service, monkeypatch)
    row = service.store.frame(frame[0])
    assert service.next_daily_refresh(row)["status"] == "waiting"
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    assert service.next_daily_refresh(row)["status"] == "preparing"
    monkeypatch.setattr(service, "converter", lambda *args: (_ for _ in ()).throw(TimeoutError()))
    service.prepare_due()
    assert service.next_daily_refresh(row)["status"] == "failed"
    # A failed prior day's slot does not make tomorrow's expected wait look broken.
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)
    assert service.next_daily_refresh(row)["status"] == "waiting"


def test_daily_weather_failure_retries_reserved_composition_before_wake(
    service, frame, monkeypatch
):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    forecast = service.providers.forecast
    monkeypatch.setattr(
        service.providers, "forecast", lambda *a: (_ for _ in ()).throw(ValueError())
    )
    service.prepare_due()
    fallback = service.store.slot_image(frame[0], "scheduled")
    assert "open_meteo" not in plan(fallback)["inputs"]
    monkeypatch.setattr(service.providers, "forecast", forecast)
    clock[0] += timedelta(minutes=16)
    service.prepare_due()
    recovered = service.store.slot_image(frame[0], "scheduled")
    assert "open_meteo" in plan(recovered)["inputs"]
    assert plan(recovered)["artworks"] == plan(fallback)["artworks"]
    assert plan(recovered)["layout"] == plan(fallback)["layout"]
    assert service.store.slot_state(frame[0], "scheduled")["attempts"] == 2
