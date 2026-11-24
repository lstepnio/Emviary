from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.battery import install_battery_routes, summarize
from emviary.owner import escape, page
from emviary.store import Store

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def readings(percentages, charging=0, usb=0):
    return [
        {
            "recorded_at": (NOW - timedelta(days=(len(percentages) - i - 1) * 2)).isoformat(),
            "percent": percent,
            "charging": charging,
            "usb_connected": usb,
            "voltage": 3.8,
        }
        for i, percent in enumerate(percentages)
    ]


def test_discharge_forecast_and_low_charge_alert():
    summary = summarize(readings([40, 38, 36, 34, 32, 30, 28, 26]), NOW)
    assert summary["days_to_charge"] == 6
    assert "Plan to charge" in summary["alert"]
    assert summary["confidence"] == "Limited"
    assert summary["span_days"] == 14
    low = summarize(readings([19]), NOW)
    assert "Time to charge" in low["alert"]
    assert low["days_to_charge"] is None


def test_charge_cycle_reset_unknown_and_stale_readings():
    history = readings([80, 75, 70, 65, 60, 55])
    assert summarize(history, NOW)["days_to_charge"] is not None
    history[-1]["usb_connected"] = 1
    assert summarize(history, NOW)["days_to_charge"] is None
    assert summarize(readings([80, 75, 70, 65, 60, 95]), NOW)["days_to_charge"] is None
    assert summarize(readings([80, 75, 70, 65, 60, 55], usb=None), NOW)["days_to_charge"] is None
    assert (
        summarize(readings([80, 75, 70, 65, 60, 55]), NOW + timedelta(days=4))["days_to_charge"]
        is None
    )
    plugged_low = summarize(readings([10], usb=1), NOW)
    assert plugged_low["alert"] is None


def test_insufficient_flat_noisy_and_robust_history():
    assert summarize(readings([40, 37, 34, 31]), NOW)["days_to_charge"] is None
    assert summarize(readings([40] * 6), NOW)["days_to_charge"] is None
    assert summarize(readings([40, 39, 40, 39, 38, 37]), NOW)["days_to_charge"] is None
    # A one-point rebound and slight voltage noise do not invent a charge cycle.
    summary = summarize(readings([50, 48, 46, 47, 42, 40, 38, 36]), NOW)
    assert summary["days_to_charge"] == 16


def test_persistent_history_dedup_validity_and_retention(service, frame, monkeypatch):
    import emviary.store as store_module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(store_module, "datetime", Clock)
    frame_id, _ = frame
    service.store.telemetry(frame_id, 52, "v1", "", "", 3.9, False, False)
    service.store.telemetry(frame_id, 51, "v1", "", "", 3.8, False, False)
    service.store.telemetry(frame_id, 999, "v1", "", "")
    restored = Store(service.store.path)
    history = restored.battery_samples(frame_id)
    assert len(history) == 1 and history[0]["percent"] == 51
    assert history[0]["voltage"] == 3.8
    old = NOW - timedelta(days=366)
    with restored.connect() as db:
        db.execute(
            """INSERT INTO battery_samples
                   (frame_id,recorded_at,bucket,percent) VALUES(?,?,?,?)""",
            (frame_id, old.isoformat(), int(old.timestamp()) // 900, 100),
        )
    restored.telemetry(frame_id, 50, "v1", "", "")
    assert len(restored.battery_samples(frame_id)) == 1
    assert restored.battery_samples(frame_id)[0]["charging"] is None


def test_route_requires_owner_session_and_escapes_frame_ids(service):
    service.store.add_frame("<script>alert(1)</script>", service.settings.config.frame_defaults)
    app = FastAPI()

    def require(request):
        if request.headers.get("owner") != "yes":
            raise HTTPException(401)

    install_battery_routes(app, service, require, escape, page)
    with TestClient(app) as client:
        assert client.get("/manage/battery").status_code == 401
        response = client.get("/manage/battery", headers={"owner": "yes"})
        assert response.status_code == 200
        assert "<script>alert" not in response.text
        assert "&lt;script&gt;" in response.text
        assert response.headers["cache-control"] == "no-store"


def test_real_image_304_persists_optional_power_headers(service, frame):
    frame_id, token = frame
    service.prepare(frame_id, "2026-10-08")
    service.refill_pending = lambda **kwargs: None
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Firmware-Version": "v1",
        "X-Battery-Percentage": "48",
        "X-Battery-Voltage": "3820",
        "X-Battery-Charging": "false",
        "X-USB-Connected": "false",
    }
    with TestClient(create_app(service, schedule=False)) as client:
        response = client.get("/v1/image", headers=headers)
        assert response.status_code == 200
        headers["If-None-Match"] = response.headers["etag"]
        assert client.get("/v1/image", headers=headers).status_code == 304
    samples = service.store.battery_samples(frame_id)
    assert len(samples) == 1
    assert samples[0]["voltage"] == 3.82 and samples[0]["charging"] == 0


def test_inflight_delivery_after_frame_removal_does_not_leave_queue_or_fail(service, frame):
    with service.store.connect() as db:
        db.execute("DELETE FROM frames WHERE id=?", (frame[0],))
    service.image_delivered(frame[0], 1, 50, "test", "", "", 3.9, False, False)
    assert service.store.pending_refills() == []
    assert service.store.battery_samples(frame[0]) == []


def slow_daily_history():
    # Similar to the observed month-long 98% -> 94% decline, including
    # quantization plateaus and one-point rebounds.
    percentages = [98] * 8 + [97] * 8 + [96] * 8 + [95] * 7 + [94] * 7
    samples = readings(percentages)
    for index, sample in enumerate(samples):
        sample["recorded_at"] = (NOW - timedelta(days=len(samples) - index - 1)).isoformat()
    samples[24]["percent"] += 1
    return samples


def test_slow_month_long_discharge_shows_bounded_trend():
    result = summarize(slow_daily_history(), NOW)
    assert result["sample_count"] == result["daily_sample_count"] == 38
    assert result["span_days"] == 37
    assert result["drop_points"] == 4
    assert result["estimate_label"] == "Over one year at the recent rate"
    assert result["days_to_charge"] is None
    assert result["confidence"] == "Limited"
    assert "not a prediction of battery life" in result["estimate_reason"]
    assert result["alert"] is None


def test_small_decline_can_support_a_limited_near_term_estimate():
    history = slow_daily_history()
    for sample in history:
        sample["percent"] -= 70
    result = summarize(history, NOW)
    assert result["days_to_charge"] is not None
    assert 20 < result["days_to_charge"] < 60
    assert result["estimate_label"] is None
    assert result["confidence"] == "Limited"


def test_horizon_does_not_hide_noisy_readings():
    history = slow_daily_history()
    for index, sample in enumerate(history[:-1]):
        sample["percent"] = 94 + (index % 3) * 2
    result = summarize(history, NOW)
    assert result["estimate_label"] is None
    assert result["days_to_charge"] is None


def test_missing_estimates_explain_the_actual_blocker():
    assert "no battery" in summarize([], NOW)["estimate_reason"].lower()
    assert "five days" in summarize(readings([50, 49, 48]), NOW)["estimate_reason"]
    assert "changed by 0" in summarize(readings([50] * 8), NOW)["estimate_reason"]
    assert (
        "Unplug"
        in summarize(slow_daily_history()[:-1] + readings([94], usb=1), NOW)["estimate_reason"]
    )
    assert "does not confirm" in summarize(readings([50] * 8, usb=None), NOW)["estimate_reason"]
    assert "fresh" in summarize(slow_daily_history(), NOW + timedelta(days=4))["estimate_reason"]


def test_unknown_power_and_long_contact_gaps_break_discharge_evidence():
    for key in ("charging", "usb_connected"):
        history = slow_daily_history()
        history[-2][key] = None
        result = summarize(history, NOW)
        assert result["sample_count"] == 1
        assert result["estimate_label"] is None
        assert result["days_to_charge"] is None
    history = slow_daily_history()
    for sample in history[:-2]:
        sample["recorded_at"] = (
            datetime.fromisoformat(sample["recorded_at"]) - timedelta(days=5)
        ).isoformat()
    result = summarize(history, NOW)
    assert result["sample_count"] == 2
    assert result["estimate_label"] is None


def test_repeated_wakes_do_not_supply_the_required_daily_readings():
    history = readings([98, 97, 96, 95, 94])
    for sample in history[1:-1]:
        sample["recorded_at"] = history[0]["recorded_at"]
    result = summarize(history, NOW)
    assert result["daily_sample_count"] < 5
    assert result["estimate_label"] is None
    assert result["days_to_charge"] is None


def test_battery_page_shows_slow_trend_and_stale_reason(service, frame, monkeypatch):
    import emviary.battery as battery

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(battery, "datetime", Clock)
    history = slow_daily_history()
    monkeypatch.setattr(service.store, "battery_samples", lambda _: history)
    app = FastAPI()
    install_battery_routes(app, service, lambda _: None, escape, page)
    with TestClient(app) as client:
        response = client.get(f"/manage/battery?frame={frame[0]}")
        assert response.status_code == 200
        assert "Over one year at the recent rate" in response.text
        assert "not a prediction of battery life" in response.text
        assert "38 daily unplugged readings" in response.text
        assert "Insufficient history" not in response.text
        assert response.headers["cache-control"] == "no-store"
        for sample in history:
            sample["recorded_at"] = (
                datetime.fromisoformat(sample["recorded_at"]) - timedelta(days=5)
            ).isoformat()
        stale = client.get(f"/manage/battery?frame={frame[0]}")
        assert "Estimate not ready" in stale.text
        assert "fresh battery reading" in stale.text
        assert "Over one year" not in stale.text


def test_warning_thresholds_hysteresis_power_and_stale():
    from emviary.battery import warning_state

    assert not warning_state(readings([26]), NOW)["active"]
    assert warning_state(readings([25]), NOW)["label"] == "Charge soon"
    assert warning_state(readings([25, 27]), NOW)["active"]
    assert not warning_state(readings([25, 28]), NOW)["active"]
    assert not warning_state(readings([27]), NOW)["active"]
    assert warning_state(readings([20]), NOW)["label"] == "Time to charge"
    assert warning_state(readings([10]), NOW)["label"] == "Battery very low"
    assert not warning_state(readings([10], usb=1), NOW)["active"]
    assert not warning_state(readings([10], charging=1), NOW)["active"]
    history = readings([20, 27])
    history[0]["usb_connected"] = 1
    assert not warning_state(history, NOW)["active"]
    stale = warning_state(readings([20]), NOW + timedelta(days=4))
    assert stale["stale"] and stale["label"] == "Last reported: time to charge"
    assert not warning_state(readings([999]), NOW)["active"]
    assert not warning_state([], NOW)["active"]


def test_warning_notice_is_actionable_and_escapes():
    from emviary.battery import warning_badge, warning_notice

    summary = summarize(readings([25]), NOW)
    assert "25% · Charge soon" in warning_badge(summary, escape)
    notice = warning_notice(summary, escape)
    assert 'role="status"' in notice and "/guide#power" in notice
    assert "USB-C" in notice and "Last reported:" in notice
    assert warning_notice(summarize(readings([60]), NOW), escape) == ""
