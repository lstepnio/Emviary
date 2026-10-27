import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from emviary.diagnostics import management_alerts, management_alerts_section, parse_metrics
from emviary.owner import escape


def update_frame(service, frame_id, **values):
    with service.store.connect() as db:
        for column, value in values.items():
            db.execute(f"UPDATE frames SET {column}=? WHERE id=?", (value, frame_id))
    return service.store.frame(frame_id)


def codes(service, frame, now):
    return {item[0] for item in management_alerts(service, frame, now)}


def test_sleep_schedule_grace_and_contact_recovery(service, frame):
    frame_id, _ = frame
    zone = ZoneInfo("America/Denver")
    now = datetime(2026, 10, 12, 3, 15, tzinfo=zone).astimezone(UTC)
    row = update_frame(
        service,
        frame_id,
        created_at=(now - timedelta(days=3)).isoformat(),
        last_contact=(now - timedelta(days=1)).isoformat(),
    )
    assert "scheduled_refresh" not in codes(service, row, now + timedelta(minutes=44))
    assert "scheduled_refresh" in codes(service, row, now + timedelta(minutes=45))
    detail = next(
        a[2]
        for a in management_alerts(service, row, now + timedelta(minutes=45))
        if a[0] == "scheduled_refresh"
    )
    assert "cached artwork" in detail and "green button" in detail
    assert "right white button" not in detail
    row = update_frame(service, frame_id, last_contact=now.isoformat())
    assert "scheduled_refresh" not in codes(service, row, now + timedelta(hours=12))
    row = update_frame(service, frame_id, last_contact=None, created_at=now.isoformat())
    assert "scheduled_refresh" not in codes(service, row, now - timedelta(minutes=1))


def test_dst_fall_back_uses_local_schedule_not_24_hour_contact_age(service, frame):
    frame_id, _ = frame
    zone = ZoneInfo("America/Denver")
    previous = datetime(2026, 10, 31, 3, 15, tzinfo=zone).astimezone(UTC)
    wake = datetime(2026, 11, 1, 3, 15, tzinfo=zone).astimezone(UTC)
    assert wake - previous == timedelta(hours=25)
    row = update_frame(
        service,
        frame_id,
        created_at=(previous - timedelta(days=1)).isoformat(),
        last_contact=previous.isoformat(),
    )
    assert "scheduled_refresh" not in codes(service, row, wake + timedelta(minutes=44))
    assert "scheduled_refresh" in codes(service, row, wake + timedelta(minutes=45))


def test_previous_date_weather_recovery_and_disabled_weather(service, frame):
    frame_id, _ = frame
    row = service.store.frame(frame_id)
    now = service.clock()
    service.store.save_snapshot(
        row["site_id"],
        "open_meteo",
        "2026-10-08",
        {"local_date": "2026-10-07", "fetched_at": (now - timedelta(days=1)).isoformat()},
        now.isoformat(),
    )
    assert "stale_weather" in codes(service, row, now)
    service.store.save_snapshot(
        row["site_id"],
        "open_meteo",
        "2026-10-08",
        {"local_date": "2026-10-08", "fetched_at": now.isoformat()},
        now.isoformat(),
    )
    assert "stale_weather" not in codes(service, row, now)
    policy = json.loads(row["policy"])
    policy["weather_cues"] = False
    row = update_frame(service, frame_id, policy=json.dumps(policy))
    assert "stale_weather" not in codes(service, row, now + timedelta(days=1))


def test_daily_forecast_can_remain_on_sleeping_panel_all_day(service, frame):
    frame_id, _ = frame
    row = service.store.frame(frame_id)
    zone = ZoneInfo("America/Denver")
    fetched = datetime(2026, 10, 8, 2, 30, tzinfo=zone).astimezone(UTC)
    service.store.save_snapshot(
        row["site_id"],
        "open_meteo",
        "2026-10-08",
        {"local_date": "2026-10-08", "fetched_at": fetched.isoformat()},
        fetched.isoformat(),
    )
    afternoon = datetime(2026, 10, 8, 15, tzinfo=zone).astimezone(UTC)
    assert "stale_weather" not in codes(service, row, afternoon)


def test_weather_free_rebuild_after_provider_expiry_is_relevant(service, frame):
    frame_id, _ = frame
    row = service.store.frame(frame_id)
    fetched = datetime(2026, 10, 8, 2, 30, tzinfo=ZoneInfo("America/Denver"))
    service.store.save_snapshot(
        row["site_id"],
        "open_meteo",
        "2026-10-08",
        {"local_date": "2026-10-08", "fetched_at": fetched.isoformat()},
        fetched.isoformat(),
    )
    assert "stale_weather" not in codes(service, row, service.clock())
    # Providers return no forecast, so the rebuild is an honest weather-free fallback.
    service.prepare(frame_id)
    assert "stale_weather" in codes(service, row, service.clock())
    refreshed = service.clock() + timedelta(minutes=1)
    service.store.save_snapshot(
        row["site_id"],
        "open_meteo",
        "2026-10-08",
        {"local_date": "2026-10-08", "fetched_at": refreshed.isoformat()},
        refreshed.isoformat(),
    )
    assert "stale_weather" not in codes(service, row, refreshed)


def test_preparation_failure_recovers_and_does_not_show_raw_error(service, frame):
    frame_id, _ = frame
    now = service.clock()
    row = service.store.frame(frame_id)
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO jobs(frame_id,local_date,revision,profile_hash,plan,status,"
            "finished_at,error) VALUES(?,?,1,'hash','{}','failed',?,'secret <trace>')",
            (frame_id, "2026-10-08", now.isoformat()),
        )
    assert "image_preparation" in codes(service, row, now)
    html = management_alerts_section(service, row, escape, now)
    assert "secret" not in html and "<trace>" not in html
    with service.store.connect() as db:
        db.execute("UPDATE jobs SET status='complete' WHERE frame_id=?", (frame_id,))
    assert "image_preparation" not in codes(service, row, now)


def test_scheduled_preparation_error_is_bounded_and_cleared(service, frame):
    frame_id, _ = frame
    now = service.clock()
    row = service.store.frame(frame_id)
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO prepared_slots(frame_id,purpose,last_attempt_at,error) "
            "VALUES(?,'scheduled',?,'ValueError')",
            (frame_id, now.isoformat()),
        )
    assert "image_preparation" in codes(service, row, now)
    assert "image_preparation" not in codes(service, row, now + timedelta(days=3))
    with service.store.connect() as db:
        db.execute("UPDATE prepared_slots SET error=NULL WHERE frame_id=?", (frame_id,))
    assert "image_preparation" not in codes(service, row, now)


def test_only_explicit_recent_ota_report_is_a_firmware_failure(service, frame):
    frame_id, _ = frame
    now = service.clock()
    row = service.store.frame(frame_id)

    def report(metrics):
        with service.store.connect() as db:
            db.execute(
                "INSERT INTO device_samples(frame_id,recorded_at,metrics) VALUES(?,?,?)",
                (frame_id, now.isoformat(), json.dumps(metrics)),
            )

    report({"previous_result": "failed", "reset_reason": 4})
    assert "firmware_update" not in codes(service, row, now)
    report({"firmware_update_result": "failed", "firmware_update_version": "<v1>"})
    assert "firmware_update" in codes(service, row, now)
    html = management_alerts_section(service, row, escape, now)
    assert "&lt;v1&gt;" in html and "<v1>" not in html
    assert "firmware_update" not in codes(service, row, now + timedelta(days=3))
    report({"firmware_update_result": "success"})
    assert "firmware_update" not in codes(service, row, now)
    report({"firmware_update_result": "retry_held"})
    assert "firmware_update" in codes(service, row, now)


def test_ota_metrics_are_bounded():
    assert parse_metrics('{"firmware_update_result":"unknown"}') is None
    assert parse_metrics(json.dumps({"firmware_update_version": "v" * 33})) is None
    assert parse_metrics('{"firmware_update_version":"bad\\n"}') is None
    assert parse_metrics('{"firmware_update_result":"retry_held"}') == {
        "firmware_update_result": "retry_held"
    }


def test_midnight_forecast_does_not_need_to_satisfy_future_wake(service, frame):
    row = service.store.frame(frame[0])
    now = datetime(2026, 10, 20, 0, 50, tzinfo=ZoneInfo("America/Denver")).astimezone(UTC)
    fetched = now - timedelta(minutes=50)
    service.store.save_snapshot(
        row["site_id"],
        "open_meteo",
        "2026-10-20",
        {"local_date": "2026-10-20", "fetched_at": fetched.isoformat()},
        fetched.isoformat(),
    )
    assert "stale_weather" not in codes(service, row, now)
    # Once daily preparation is due, the midnight cache no longer suffices.
    after_prepare = datetime(2026, 10, 20, 2, 31, tzinfo=ZoneInfo("America/Denver"))
    assert "stale_weather" in codes(service, row, after_prepare.astimezone(UTC))


def test_yesterdays_panel_forecast_survives_midnight_until_preparation_due(service, frame):
    row = service.store.frame(frame[0])
    zone = ZoneInfo("America/Denver")
    fetched = datetime(2026, 10, 19, 2, 30, tzinfo=zone)
    service.store.save_snapshot(
        row["site_id"],
        "open_meteo",
        "2026-10-19",
        {"local_date": "2026-10-19", "fetched_at": fetched.isoformat()},
        fetched.isoformat(),
    )
    assert "stale_weather" not in codes(service, row, datetime(2026, 10, 20, 0, 5, tzinfo=zone))
