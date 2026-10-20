import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

from emviary.backup_validation import MANIFEST, file_digest

spec = importlib.util.spec_from_file_location(
    "pull_verified_backup", Path(__file__).resolve().parents[1] / "tools/pull_verified_backup.py"
)
puller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(puller)


def archive_backup(source, output):
    with tarfile.open(output, "w") as archive:
        archive.add(source, arcname=".")
    return output


@pytest.mark.parametrize(
    "name,kind",
    [
        ("/absolute", tarfile.REGTYPE),
        ("../escape", tarfile.REGTYPE),
        ("sub/../../escape", tarfile.REGTYPE),
        ("link", tarfile.SYMTYPE),
        ("hardlink", tarfile.LNKTYPE),
        ("device", tarfile.CHRTYPE),
    ],
)
def test_unsafe_archive_rejected(tmp_path, name, kind):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as output:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "../../escape"
        output.addfile(member, io.BytesIO())
    with pytest.raises(ValueError):
        puller.extract_private(archive, tmp_path / "private")
    assert not (tmp_path / "escape").exists()


def test_publish_validates_restore_permissions_and_is_idempotent(service, tmp_path):
    source = Path(service.backup(tmp_path / "source"))
    archive = archive_backup(source, tmp_path / "backup.tar")
    destination = tmp_path / "destination"
    digest = file_digest(source / MANIFEST)
    report = puller.publish_archive(archive, destination, "2026-10-12", digest)
    assert report["restore_rehearsal"] == "passed"
    assert report["network_providers"] == "disabled"
    assert report["transfer_status"] == "downloaded"
    target = destination / "2026-10-12"
    before = {
        p.relative_to(target): (p.stat().st_mtime_ns, file_digest(p))
        for p in target.rglob("*")
        if p.is_file()
    }
    report = puller.publish_archive(archive, destination, "2026-10-12", digest)
    assert report["transfer_status"] == "already_present"
    assert before == {
        p.relative_to(target): (p.stat().st_mtime_ns, file_digest(p))
        for p in target.rglob("*")
        if p.is_file()
    }
    assert all(
        p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600)
        for p in [destination, target, *target.rglob("*")]
    )


def test_corrupt_copy_and_collision_never_publish_or_replace(service, tmp_path):
    source = Path(service.backup(tmp_path / "source"))
    digest = file_digest(source / MANIFEST)
    destination = tmp_path / "destination"
    archive = archive_backup(source, tmp_path / "original.tar")
    puller.publish_archive(archive, destination, "daily", digest)
    original = (destination / "daily" / "site.json").read_bytes()
    (source / "site.json").write_bytes(b"broken")
    bad = archive_backup(source, tmp_path / "bad.tar")
    with pytest.raises(ValueError):
        puller.publish_archive(bad, destination, "daily", digest)
    assert (destination / "daily" / "site.json").read_bytes() == original
    with pytest.raises(ValueError):
        puller.publish_archive(archive, destination, "different", "0" * 64)
    assert not (destination / "different").exists()
    assert not list(destination.glob(".pull-*"))


def test_duplicate_and_disk_limit_rejected(tmp_path):
    archive = tmp_path / "duplicate.tar"
    with tarfile.open(archive, "w") as output:
        for _ in range(2):
            member = tarfile.TarInfo("file")
            member.size = 4
            output.addfile(member, io.BytesIO(b"data"))
    with pytest.raises(ValueError, match="duplicate"):
        puller.extract_private(archive, tmp_path / "duplicate")
    with pytest.raises(ValueError, match="disk limit"):
        puller.extract_private(archive, tmp_path / "limited", max_bytes=3)


def test_pull_reports_remote_success_only_after_verified_publication(
    service, tmp_path, monkeypatch
):
    import json
    import shutil
    from types import SimpleNamespace

    source = Path(service.backup(tmp_path / "source"))
    archive = archive_backup(source, tmp_path / "backup.tar")
    digest = file_digest(source / MANIFEST)
    destination = tmp_path / "destination"
    updates = []

    def ssh(command, **kwargs):
        assert command == "python3 -"
        if kwargs["input"] == puller.REMOTE_SELECT.encode():
            return SimpleNamespace(
                stdout=json.dumps({"name": "daily", "manifest_sha256": digest}).encode()
            )
        assert (destination / "daily" / "COMPLETE").is_file()
        updates.append(kwargs["input"].decode())
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(puller, "ssh_run", ssh)
    monkeypatch.setattr(
        puller, "download_archive", lambda command, target, limit: shutil.copyfile(archive, target)
    )
    report = puller.pull(destination)
    assert report["restore_rehearsal"] == "passed" and len(updates) == 1
    assert "offhost-backup.json" in updates[0]
    assert str(destination) not in updates[0]
    assert json.loads((destination / ".last-pull.json").read_text())["status"] == "verified"

    (source / "site.json").write_bytes(b"corrupt")
    archive_backup(source, archive)
    with pytest.raises(ValueError):
        puller.pull(destination)
    assert len(updates) == 1


def test_cli_failure_status_is_private_and_never_logs_remote_details(tmp_path, monkeypatch, capsys):
    import json
    import os
    import sys

    destination = tmp_path / "destination"
    monkeypatch.setattr(sys, "argv", ["pull_verified_backup.py", "--destination", str(destination)])

    def fail(*args):
        raise RuntimeError("remote details must stay private")

    monkeypatch.setattr(puller, "pull", fail)
    previous_umask = os.umask(0o077)
    try:
        with pytest.raises(SystemExit) as error:
            puller.main()
    finally:
        os.umask(previous_umask)
    assert error.value.code == 1
    assert "remote details" not in capsys.readouterr().err
    status = destination / ".last-pull.json"
    assert json.loads(status.read_text())["status"] == "failed"
    assert status.stat().st_mode & 0o777 == 0o600


def test_host_selection_skips_unreadable_invalid_and_future_markers(tmp_path, monkeypatch, capsys):
    import json
    from datetime import UTC, datetime, timedelta

    root = tmp_path / "remote"
    root.mkdir()
    now = datetime.now(UTC)
    digest = __import__("hashlib").sha256(b"{}").hexdigest()

    def record(name, stamp, **extra):
        folder = root / name
        folder.mkdir()
        (folder / MANIFEST).write_text("{}")
        marker = {
            "created_at": stamp,
            "manifest_sha256": digest,
            "restore_rehearsal": "passed",
            **extra,
        }
        (folder / "COMPLETE").write_text(json.dumps(marker))
        return folder

    record("valid", now.isoformat())
    record("future", (now + timedelta(hours=2)).isoformat())
    record("bad-hash", now.isoformat(), manifest_sha256="0" * 64)
    bad = record("corrupt", now.isoformat())
    (bad / "COMPLETE").write_text("[]")
    private = record("private", now.isoformat())
    original = Path.is_file

    def is_file(path):
        if path == private / "COMPLETE":
            raise PermissionError("private status")
        return original(path)

    monkeypatch.setattr(Path, "is_file", is_file)
    script = puller.REMOTE_SELECT.replace("Path('/docker/backups/emviary')", f"Path({str(root)!r})")
    exec(compile(script, "remote-selector", "exec"), {})
    assert json.loads(capsys.readouterr().out) == {"name": "valid", "manifest_sha256": digest}
    (root / "valid" / "COMPLETE").unlink()
    with pytest.raises(RuntimeError, match="No completed backup"):
        exec(compile(script, "remote-selector", "exec"), {})
