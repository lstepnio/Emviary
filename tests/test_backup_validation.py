import json
import sqlite3
from pathlib import Path

import pytest

from emviary.backup_validation import file_digest, verify_backup, write_manifest
from emviary.cli import main


def reseal(path):
    write_manifest(path)
    (path / "COMPLETE").write_text(
        json.dumps({"manifest_sha256": file_digest(path / "integrity-manifest.json")})
    )


def test_backup_rehearsal_keeps_delivered_navigation_and_source_untouched(service, frame, tmp_path):
    first = service.prepare(frame[0], "2026-10-07", offline=True)
    service.store.telemetry(frame[0], None, "v2.19.0", "", '"' + first["body_hash"] + '"')
    with service.store.connect() as db:
        db.execute("UPDATE frames SET max_delivered_image_id=? WHERE id=?", (first["id"], frame[0]))
    service.prepare(frame[0], "2026-10-08", offline=True)
    backup = Path(service.backup(tmp_path / "backup"))
    before = {p.relative_to(backup): file_digest(p) for p in backup.rglob("*") if p.is_file()}
    result = verify_backup(backup)
    assert result["frames"] == 1 and result["retained_images"] >= 2
    assert result["delivered_images"] == 1
    assert result["network_providers"] == "disabled"
    assert before == {
        p.relative_to(backup): file_digest(p) for p in backup.rglob("*") if p.is_file()
    }
    assert service.cache_path(first["path"]).is_file()
    assert backup.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in backup.rglob("*") if p.is_file())
    manifest = json.loads((backup / "integrity-manifest.json").read_text())
    assert manifest["files"]["site.json"]["size"] == (backup / "site.json").stat().st_size


def test_corruption_missing_manifest_extra_file_and_symlinks_rejected(service, tmp_path):
    backup = Path(service.backup(tmp_path / "backup"))
    site = backup / "site.json"
    original = site.read_bytes()
    site.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="integrity"):
        verify_backup(backup)
    site.write_bytes(original)
    (backup / "unexpected").write_text("extra")
    with pytest.raises(ValueError, match="integrity"):
        verify_backup(backup)
    (backup / "unexpected").unlink()
    (backup / "linked").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symbolic link"):
        verify_backup(backup)
    (backup / "linked").unlink()
    (backup / "integrity-manifest.json").unlink()
    with pytest.raises(ValueError, match="legacy"):
        verify_backup(backup)


def test_database_image_reference_and_panel_bytes_verified_even_after_reseal(
    service, frame, tmp_path
):
    image = service.prepare(frame[0], offline=True)
    backup = Path(service.backup(tmp_path / "backup"))
    panel = backup / "active-cache" / Path(image["path"]).name
    original = panel.read_bytes()
    panel.write_bytes(b"not a panel image")
    reseal(backup)
    with pytest.raises(ValueError):
        verify_backup(backup)
    panel.write_bytes(original)
    panel.unlink()
    reseal(backup)
    with pytest.raises(ValueError, match="missing a retained image"):
        verify_backup(backup)


def test_missing_art_and_bad_sqlite_fail_restore_rehearsal(service, tmp_path):
    backup = Path(service.backup(tmp_path / "backup"))
    artwork = service.settings.artworks[0]
    (backup / "art" / artwork["asset"]).unlink()
    reseal(backup)
    with pytest.raises(ValueError, match="restore rehearsal"):
        verify_backup(backup)
    (backup / "emviary.sqlite3").write_bytes(b"not sqlite")
    reseal(backup)
    with pytest.raises(ValueError, match="database"):
        verify_backup(backup)


def test_backup_failure_is_not_published_and_existing_backup_not_overwritten(
    service, frame, tmp_path
):
    image = service.prepare(frame[0], offline=True)
    backup = Path(service.backup(tmp_path / "backup"))
    with pytest.raises(ValueError, match="already exists"):
        service.backup(backup)
    service.cache_path(image["path"]).unlink()
    failed = tmp_path / "failed"
    with pytest.raises(ValueError, match="missing a retained image"):
        service.backup(failed)
    assert not failed.exists()
    assert not list(tmp_path.glob(".emviary-backup-*"))


def test_hidden_history_missing_bytes_allowed_but_active_required(service, frame, tmp_path):
    first = service.prepare(frame[0], "2026-10-07", offline=True)
    service.prepare(frame[0], "2026-10-08", offline=True)
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (first["id"],))
    service.cache_path(first["path"]).unlink()
    service.cache_path(first["preview_path"]).unlink()
    backup = Path(service.backup(tmp_path / "backup"))
    assert verify_backup(backup)["retained_images"] == 1


def test_cli_verifies_without_initializing_live_service(service, tmp_path, monkeypatch, capsys):
    backup = Path(service.backup(tmp_path / "backup"))
    monkeypatch.setattr("sys.argv", ["emviary", "verify-backup", str(backup)])
    monkeypatch.setattr("emviary.cli.Service", lambda: pytest.fail("Live service initialized"))
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["restore_rehearsal"] == "passed"
    assert "token_hash" not in result


def test_unsafe_manifest_path_and_database_reference_fail(service, frame, tmp_path):
    service.prepare(frame[0], offline=True)
    backup = Path(service.backup(tmp_path / "backup"))
    with sqlite3.connect(backup / "emviary.sqlite3") as db:
        db.execute("UPDATE images SET path='../outside.epdgz'")
    reseal(backup)
    with pytest.raises(ValueError, match="restore rehearsal"):
        verify_backup(backup)
    manifest = json.loads((backup / "integrity-manifest.json").read_text())
    manifest["files"]["../escape"] = {"size": 1, "sha256": "0" * 64}
    (backup / "integrity-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="integrity"):
        verify_backup(backup)
