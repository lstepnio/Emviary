import json
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_management_alerts import update_frame
from test_owner import sign_in

from emviary import cli
from emviary.api import create_app
from emviary.backup_status import backup_health, backup_health_section
from emviary.owner import escape
from emviary.readiness import readiness_summary
from emviary.ui import local_time


def verified_backups(service, stamp):
    folder = service.settings.backup_dir / "verified"
    folder.mkdir(exist_ok=True)
    (folder / "COMPLETE").write_text(
        json.dumps({"restore_rehearsal": "passed", "created_at": stamp.isoformat()})
    )
    (service.settings.data_dir / "offhost-backup.json").write_text(
        json.dumps({"created_at": stamp.isoformat()})
    )


def healthy_service(service, frame):
    row = service.store.frame(frame[0])
    policy = json.loads(row["policy"])
    policy["weather_cues"] = False
    update_frame(
        service,
        frame[0],
        policy=json.dumps(policy),
        created_at=(service.clock() - timedelta(days=1)).isoformat(),
        last_contact=service.clock().isoformat(),
    )
    row = service.store.frame(frame[0])
    day = (
        service.clock()
        .astimezone(ZoneInfo(service.settings.config.site(row["site_id"]).timezone))
        .date()
    )
    service.prepare_due(now=service.daily_schedule(row, day)["prepare_at"])
    verified_backups(service, service.clock())


def test_backup_freshness_boundary_and_future_clock_are_explicit(service):
    now = service.clock()
    verified_backups(service, now - timedelta(hours=36))
    health = backup_health(service.settings.backup_dir, service.settings.data_dir, now)
    assert health["local_status"] == health["independent_status"] == "stale"
    html = backup_health_section(service, escape, local_time)
    assert "Verified backup is overdue" in html
    assert "Independent copy is overdue" in html
    verified_backups(service, now - timedelta(hours=36) + timedelta(seconds=1))
    health = backup_health(service.settings.backup_dir, service.settings.data_dir, now)
    assert health["local_status"] == health["independent_status"] == "fresh"
    verified_backups(service, now + timedelta(hours=1))
    health = backup_health(service.settings.backup_dir, service.settings.data_dir, now)
    assert health["local_status"] == health["independent_status"] == "invalid"


def test_latest_failed_pull_does_not_erase_previous_verified_copy(service):
    now = service.clock()
    verified_backups(service, now - timedelta(hours=1))
    path = service.settings.data_dir / "offhost-backup-attempt.json"
    for age, expected in ((timedelta(), "failed"), (timedelta(hours=2), "fresh")):
        path.write_text(json.dumps({"status": "failed", "checked_at": (now - age).isoformat()}))
        health = backup_health(service.settings.backup_dir, service.settings.data_dir, now)
        assert health["independent_status"] == expected
        assert health["independent"] == (now - timedelta(hours=1)).isoformat()
    path.write_text("invalid")
    health = backup_health(service.settings.backup_dir, service.settings.data_dir, now)
    assert health["independent_status"] == "unavailable"


def test_readiness_auth_health_and_no_preparation_side_effects(
    service, frame, tmp_path, monkeypatch
):
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.get("/manage/readiness").status_code == 401
    assert (
        anonymous.get(
            "/manage/readiness", headers={"Authorization": "Bearer " + frame[1]}
        ).status_code
        == 401
    )
    client, _ = sign_in(service, tmp_path, monkeypatch)
    response = client.get("/manage/readiness")
    assert response.status_code == 503
    assert response.json()["backups"]["local_status"] == "missing"
    healthy_service(service, frame)
    calls = service.providers.calls
    with service.store.connect() as db:
        job_count = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
    response = client.get("/manage/readiness")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "ready"
    assert response.json()["frames"] == [{"id": frame[0], "alerts": []}]
    assert service.providers.calls == calls
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == job_count
    # Liveness remains independent from backup and frame readiness.
    (service.settings.data_dir / "offhost-backup.json").unlink()
    assert client.get("/manage/readiness").status_code == 503
    assert client.get("/healthz").status_code == 200


def test_cli_readiness_matches_shared_summary_and_failure_exit(service, frame, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Service", lambda: service)
    monkeypatch.setattr("sys.argv", ["emviary", "readiness"])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    assert json.loads(capsys.readouterr().out) == readiness_summary(service)
    healthy_service(service, frame)
    cli.main()
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_backup_destination_write_permission_is_required(service, monkeypatch):
    from emviary import backup_status

    verified_backups(service, service.clock())
    monkeypatch.setattr(backup_status.os, "access", lambda *args: False)
    health = backup_health(service.settings.backup_dir, service.settings.data_dir, service.clock())
    assert health["local_status"] == "unwritable"
    assert "Backup folder is not writable" in backup_health_section(service, escape, local_time)
