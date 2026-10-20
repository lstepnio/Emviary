import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary import usb_recovery
from emviary.api import create_app
from emviary.backup_status import backup_health
from emviary.diagnostics import device_readings, management_alerts
from emviary.ui import local_time


def complete(root, name, value):
    folder = root / name
    folder.mkdir()
    (folder / "COMPLETE").write_text(json.dumps(value))
    return folder


def test_recovery_survives_private_backup_folder_and_lists_other_backups(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    complete(
        service.settings.backup_dir,
        "valid",
        {
            "restore_rehearsal": "passed",
            "created_at": "2026-10-08T10:00:00+00:00",
        },
    )
    private = service.settings.backup_dir / "private-deployment"
    private.mkdir()
    original = Path.is_file

    def is_file(path):
        if path == private / "COMPLETE":
            raise PermissionError("private metadata")
        return original(path)

    monkeypatch.setattr(Path, "is_file", is_file)
    response = client.get("/manage/recovery?frame=" + frame[0])
    assert response.status_code == 200
    assert "Latest verified backup:" in response.text
    assert "Some backup records could not be read" in response.text
    assert "Restore firmware over USB" in response.text
    assert str(private) not in response.text


@pytest.mark.parametrize(
    "record",
    [
        [],
        None,
        True,
        42,
        "bad",
        {},
        {"restore_rehearsal": "passed", "created_at": []},
        {"restore_rehearsal": "passed", "created_at": "not-a-date"},
        {"restore_rehearsal": "passed", "created_at": "2026-10-08T10:00:00"},
    ],
)
def test_malformed_backup_and_independent_records_do_not_crash_recovery(
    service, frame, tmp_path, monkeypatch, record
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    complete(service.settings.backup_dir, "bad", record)
    (service.settings.data_dir / "offhost-backup.json").write_text(json.dumps(record))
    response = client.get("/manage/recovery")
    assert response.status_code == 200
    assert "Independent-copy status is unavailable" in response.text
    assert "Restore firmware over USB" in response.text


def test_missing_or_unreadable_backup_root_is_an_explicit_unavailable_state(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    original = Path.iterdir

    def iterdir(path):
        if path == service.settings.backup_dir:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    response = client.get("/manage/recovery")
    assert response.status_code == 200 and "Backup status is unavailable" in response.text
    assert "No readable backup with a verified restore rehearsal yet" not in response.text


def test_backup_health_orders_instants_not_timestamp_strings_and_ignores_links(service, tmp_path):
    complete(
        service.settings.backup_dir,
        "earlier",
        {
            "restore_rehearsal": "passed",
            "created_at": "2026-10-08T10:00:00+02:00",
        },
    )
    complete(
        service.settings.backup_dir,
        "later",
        {
            "restore_rehearsal": "passed",
            "created_at": "2026-10-08T09:00:00+00:00",
        },
    )
    target = complete(
        tmp_path,
        "outside",
        {
            "restore_rehearsal": "passed",
            "created_at": "2029-10-08T10:00:00+00:00",
        },
    )
    (service.settings.backup_dir / "linked").symlink_to(target, target_is_directory=True)
    health = backup_health(service.settings.backup_dir, service.settings.data_dir)
    assert health["latest_verified"] == "2026-10-08T09:00:00+00:00"


@pytest.mark.parametrize("value", [None, [], 8, "not-a-date", "2026-10-08T10:00:00"])
def test_optional_bad_timestamps_are_not_formatted_as_valid_status(value):
    assert local_time(value) == "Not reported"


def test_bad_saved_readings_do_not_break_management_or_usb_status(
    service, frame, tmp_path, monkeypatch
):
    service.store.device_sample(frame[0], {"ssid": "Saved network", "connect_ms": 1000})
    with service.store.connect() as db:
        for raw in ("not-json", "[]", "null", '{"connect_ms":"bad"}', '{"wifi_networks":[{}]}'):
            db.execute(
                "INSERT INTO device_samples(frame_id,recorded_at,metrics,firmware) VALUES(?,?,?,?)",
                (frame[0], "2026-10-09T12:00:00+00:00", raw, "v0.8.10"),
            )
        db.execute(
            "INSERT INTO device_samples(frame_id,recorded_at,metrics) VALUES(?,?,?)",
            (frame[0], "not-a-date", "{}"),
        )
        db.execute(
            "INSERT INTO battery_samples(frame_id,recorded_at,bucket,percent,voltage,"
            "charging,usb_connected) "
            "VALUES(?,?,?,?,?,?,?)",
            (frame[0], "not-a-date", 1, 80, "bad", 8, 9),
        )
    client, _ = sign_in(service, tmp_path, monkeypatch)
    for route in ("/manage", "/manage/settings", "/manage/battery", "/manage/recovery"):
        response = client.get(route + "?frame=" + frame[0])
        assert response.status_code == 200
    status = client.get("/manage/usb-recovery/status/" + frame[0])
    assert status.status_code == 200 and status.json()["connected"] is False
    assert len(device_readings(service.store, frame[0])) == 1
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM device_samples").fetchone()[0] == 7


def test_optional_weather_and_job_status_can_be_malformed_without_breaking_alerts(service, frame):
    now = service.clock()
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO provider_snapshots VALUES(?,?,?,?,?)",
            ("denver-gift", "open_meteo", "2026-10-08", "[]", now.isoformat()),
        )
        db.execute(
            "INSERT INTO prepared_slots(frame_id,purpose,error,last_attempt_at) "
            "VALUES(?,'scheduled','TimeoutError','bad-date')",
            (frame[0],),
        )
    alerts = management_alerts(service, service.store.frame(frame[0]), now)
    assert "stale_weather" in {item[0] for item in alerts}


def test_broken_usb_bundle_fails_closed_with_a_controlled_unavailable_response(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    monkeypatch.setattr(
        usb_recovery, "recovery_manifest", lambda: (_ for _ in ()).throw(TypeError())
    )
    assert client.get("/manage/recovery").status_code == 200
    for route in (
        "/manage/usb-recovery/manifest",
        "/manage/usb-recovery/status/" + frame[0],
        "/manage/usb-recovery/v0.8.10/firmware.bin",
    ):
        assert client.get(route).status_code == 503
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.get("/manage/usb-recovery/manifest").status_code == 401


def test_recovery_renders_one_target_and_no_duplicate_usb_controls(
    service, frame, tmp_path, monkeypatch
):
    token = service.store.add_frame("second-frame", service.settings.config.frame_defaults)
    directory = service.settings.data_dir / "provisioning"
    directory.mkdir()
    (directory / "second-frame.token").write_text(token)
    client, _ = sign_in(service, tmp_path, monkeypatch)
    for path in ("/manage/recovery", "/manage/recovery?frame=second-frame"):
        page = client.get(path)
        assert page.status_code == 200
        assert page.text.count('id="usb-recovery"') == 1
        assert page.text.count('<details class="manual-recovery">') == 1
    chosen = client.get("/manage/recovery?frame=second-frame").text
    assert "/manage/frames/second-frame/provision" in chosen
    assert "/manage/frames/test-frame/provision" not in chosen


def test_recovery_is_usable_before_any_frames_are_added(service, tmp_path, monkeypatch):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    response = client.get("/manage/recovery")
    assert response.status_code == 200
    assert 'id="usb-recovery"' not in response.text
    assert response.text.count("<details") == response.text.count("</details>")


def test_missing_usb_ui_files_and_unknown_frame_return_controlled_errors(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    assert client.get("/manage/usb-recovery/status/missing-frame").status_code == 404
    original = Path.is_file

    def is_file(path):
        return False if path == usb_recovery.ROOT / "recovery.js" else original(path)

    monkeypatch.setattr(Path, "is_file", is_file)
    assert client.get("/manage/usb-recovery/assets/recovery.js").status_code == 503
    assert client.get("/manage/usb-recovery/assets/not-allowed.js").status_code == 404
