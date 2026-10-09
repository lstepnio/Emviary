import base64
import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.diagnostics import diagnostics_section, parse_metrics
from emviary.owner import escape


def test_metrics_are_bounded_and_unknown_secrets_discarded():
    assert parse_metrics("invalid") is None
    assert parse_metrics("b64:!!") is None
    assert parse_metrics("x" * 2049) is None
    for value in [1, -128, "weak", True]:
        assert parse_metrics(json.dumps({"rssi_dbm": value})) is None
    assert parse_metrics('{"local_ip":"not-an-address"}') is None
    value = {"ssid": "Café", "rssi_dbm": -67, "password": "not-retained", "bssid": "omitted"}
    encoded = "b64:" + base64.b64encode(json.dumps(value).encode()).decode()
    assert parse_metrics(encoded) == {"ssid": "Café", "rssi_dbm": -67}


def test_image_requests_store_diagnostics_without_changing_navigation(service, frame):
    frame_id, token = frame
    service.prepare(frame_id)
    client = TestClient(create_app(service, schedule=False))
    metrics = {"rssi_dbm": -73, "previous_result": "success", "previous_total_ms": 31000}
    response = client.get(
        "/v1/image",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Firmware-Version": "v0.6.2",
            "X-Frame-Metrics": json.dumps(metrics),
        },
    )
    assert response.status_code == 200
    rows = service.store.device_samples(frame_id)
    assert len(rows) == 1 and json.loads(rows[0]["metrics"]) == metrics
    assert rows[0]["firmware"] == "v0.6.2"
    assert client.get("/manage/battery").status_code == 401
    assert "rssi_dbm" not in client.get("/credits.json").text
    # Malformed metadata must never prevent an otherwise valid image delivery.
    assert (
        client.get(
            "/v1/image",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Firmware-Version": "v0.6.2",
                "X-Frame-Metrics": '{"rssi_dbm":999}',
            },
        ).status_code
        == 200
    )
    assert len(service.store.device_samples(frame_id)) == 1


def test_history_is_bounded_per_frame_and_ui_escapes_network_names(service, frame):
    frame_id, _ = frame
    service.store.device_sample(frame_id, {"ssid": "<network>", "rssi_dbm": -75})
    html = diagnostics_section(service.store, frame_id, escape)
    assert "&lt;network&gt;" in html and "<network>" not in html
    assert "Weak Wi-Fi" in html and "Reported on the next connection" in html
    assert "Mountain time" in html and "+00:00" not in html
    assert "Local address" not in html and "Memory low" not in html
    assert "Wake / reset" not in html and "Network / channel" not in html
    with service.store.connect() as db:
        now = datetime.now(UTC)
        db.execute(
            "INSERT INTO device_samples(frame_id,recorded_at,metrics) VALUES(?,?,?)",
            (frame_id, (now - timedelta(days=91)).isoformat(), "{}"),
        )
        db.executemany(
            "INSERT INTO device_samples(frame_id,recorded_at,metrics) VALUES(?,?,?)",
            [(frame_id, now.isoformat(), "{}")] * 2001,
        )
    service.store.device_sample(frame_id, {"rssi_dbm": -55})
    rows = service.store.device_samples(frame_id)
    assert len(rows) == 2000
    assert all(
        datetime.fromisoformat(row["recorded_at"]) > now - timedelta(days=90) for row in rows
    )


def test_saved_network_inventory_bounds_and_secret_isolation():
    networks = [{"ssid": "😀" * 8, "password_set": True, "password": "secret"}]
    value = parse_metrics(json.dumps({"wifi_networks": networks}))
    assert value == {"wifi_networks": [{"ssid": "😀" * 8, "password_set": True}]}
    for invalid in (
        networks * 2,
        [{"ssid": str(i), "password_set": False} for i in range(6)],
        [{"ssid": "😀" * 9, "password_set": False}],
        [{"ssid": "bad\n", "password_set": False}],
        [{"ssid": "", "password_set": False}],
        [{"ssid": "Home", "password_set": "true"}],
    ):
        assert parse_metrics(json.dumps({"wifi_networks": invalid})) is None
    # Five maximum-byte Unicode names and full metrics fit the wire budget.
    metrics = {
        "wifi_networks": [{"ssid": "😀" * 7 + str(i), "password_set": True} for i in range(5)],
        "ssid": "😀" * 7 + "0",
        "rssi_dbm": -60,
        "local_ip": "192.168.100.100",
        "connect_ms": 3600000,
        "disconnects": 2147483647,
        "disconnect_reason": 255,
        "uptime_ms": 9007199254740991,
        "boot_count": 4294967295,
        "wake_cause": 16,
        "reset_reason": 32,
        "free_heap": 67108864,
        "min_free_heap": 67108864,
        "previous_result": "unchanged",
        "previous_total_ms": 3600000,
        "previous_download_ms": 3600000,
        "previous_bytes": 33554432,
        "previous_http_status": 599,
        "previous_attempts": 3,
        "channel": 14,
    }
    header = "b64:" + base64.b64encode(json.dumps(metrics).encode()).decode()
    assert len(header) <= 2048 and parse_metrics(header) == metrics


def test_owner_shows_device_only_networks_and_distinguishes_pending_changes(
    service, frame, tmp_path, monkeypatch
):
    from test_owner import sign_in

    frame_id, token = frame
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    service.prepare(frame_id)
    monkeypatch.setattr(service, "refill_pending", lambda **kwargs: None)
    metrics = {
        "ssid": "<Home>",
        "wifi_networks": [
            {"ssid": "<Home>", "password_set": True, "password": "never-store"},
            {"ssid": "Guest", "password_set": False},
        ],
    }
    headers = {
        "Authorization": "Bearer " + token,
        "X-Frame-Metrics": json.dumps(metrics),
        "X-Firmware-Version": "v0.7.6",
    }
    response = client.get("/v1/image", headers=headers)
    assert response.status_code == 200
    headers["If-None-Match"] = response.headers["etag"]
    assert client.get("/v1/image", headers=headers).status_code == 304
    assert len(service.store.device_samples(frame_id)) == 2
    assert "never-store" not in service.store.device_samples(frame_id)[-1]["metrics"]
    client.post(
        "/manage/frames/test-frame/wifi",
        data={
            "csrf": csrf,
            "ssid": "Destination",
            "password": "private-destination",
            "action": "save",
        },
    )
    html = client.get("/manage/settings").text
    assert "2 of 5 networks saved" in html and "&lt;Home&gt;" in html
    assert "Connected" in html and "Open network" in html and "Destination" in html
    assert "Last reported:" in html and "Cloud-managed networks" in html
    assert "never-store" not in html and "private-destination" not in html
    assert "<Home>" not in html
    for path in ("/", "/library", "/credits.json"):
        public = client.get(path).text
        assert "&lt;Home&gt;" not in public and "Destination" not in public
