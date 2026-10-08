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
    assert "Charge soon" in low["alert"]
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
