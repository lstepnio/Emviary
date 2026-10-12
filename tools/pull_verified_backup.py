#!/usr/bin/env python3
"""Pull and rehearse a verified Emviary backup without changing existing copies."""

import argparse
import fcntl
import json
import os
import re
import selectors
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from emviary.backup_validation import MANIFEST, file_digest, verify_backup

HOST = "lstepnio@one.majjix.com"
REMOTE_ROOT = "/docker/backups/emviary"
DEFAULT_DESTINATION = Path.home() / "Library/Application Support/Emviary/backups"
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
REMOTE_SELECT = r"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from emviary.backup_validation import MANIFEST, file_digest, verify_backup
from emviary.service import Service
root = Path('/backups')
candidates = sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink()
                     and (p / 'COMPLETE').is_file() and (p / MANIFEST).is_file()),
                    key=lambda p: p.stat().st_mtime, reverse=True)
selected = None
today = datetime.now(ZoneInfo('America/Denver')).date()
for candidate in candidates:
    try:
        marker = json.loads((candidate / 'COMPLETE').read_text())
        created = datetime.fromisoformat(marker['created_at']).astimezone(
            ZoneInfo('America/Denver'))
        if created.date() != today:
            continue
        verify_backup(candidate)
        selected = candidate
        break
    except (ValueError, KeyError, OSError, RuntimeError):
        continue
if selected is None:
    name = 'offhost-' + datetime.now(ZoneInfo('America/Denver')).date().isoformat()
    selected = Path(Service().backup(root / name))
    verify_backup(selected)
print(json.dumps({'name': selected.name, 'manifest_sha256': file_digest(selected / MANIFEST)}))
"""


def private_directory(path):
    path = Path(path).absolute()
    # A symlink in any ancestor could redirect private backup material.
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Backup destination cannot contain symbolic links")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def extract_private(archive, destination, max_bytes=None):
    """Write only regular files and directories; never follow archive links."""
    destination = private_directory(destination)
    seen, total = set(), 0
    with tarfile.open(archive, mode="r:*") as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                raise ValueError("Unsafe archive path")
            name = path.as_posix()
            if name == "." and member.isdir():
                continue
            if name in seen or name == "." or not (member.isfile() or member.isdir()):
                raise ValueError("Archive contains duplicate paths, links or unsupported entries")
            seen.add(name)
            target = destination.joinpath(*path.parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError("Archive path escapes staging directory")
            for parent in reversed(target.parents):
                if parent == destination or parent.is_relative_to(destination):
                    parent.mkdir(exist_ok=True, mode=0o700)
                    os.chmod(parent, 0o700)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(target, 0o700)
                continue
            total += member.size
            if max_bytes is not None and total > max_bytes:
                raise ValueError("Backup exceeds the configured disk limit")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError("Archive file cannot be read")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with stream, os.fdopen(fd, "wb") as output:
                shutil.copyfileobj(stream, output)
            if target.stat().st_size != member.size:
                raise ValueError("Archive file is truncated")
    return destination


def publish_archive(archive, destination, name, expected_hash, max_bytes=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", name):
        raise ValueError("Invalid remote backup name")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
        raise ValueError("Invalid remote manifest digest")
    destination = private_directory(destination)
    with tempfile.TemporaryDirectory(prefix=".pull-", dir=destination) as temporary:
        staging = extract_private(archive, Path(temporary) / "backup", max_bytes)
        if file_digest(staging / MANIFEST) != expected_hash:
            raise ValueError("Downloaded manifest differs from verified remote backup")
        report = verify_backup(staging)
        target = destination / name
        if target.exists() or target.is_symlink():
            if target.is_symlink() or file_digest(target / MANIFEST) != expected_hash:
                raise ValueError("An existing backup has this name with different contents")
            verify_backup(target)
            return {**report, "transfer_status": "already_present", "backup": name}
        # Caller holds the destination lock; rename publishes the complete private tree.
        staging.rename(target)
        return {**report, "transfer_status": "downloaded", "backup": name}


def ssh_run(command, **kwargs):
    try:
        return subprocess.run(
            ["ssh", *SSH_OPTIONS, HOST, command],
            check=True,
            stderr=subprocess.PIPE,
            timeout=1200,
            **kwargs,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Remote backup operation failed") from exc


def download_archive(command, archive, max_bytes=None):
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output, tempfile.TemporaryFile() as errors:
        with subprocess.Popen(
            ["ssh", *SSH_OPTIONS, HOST, command], stdout=subprocess.PIPE, stderr=errors
        ) as process:
            try:
                deadline, total = time.monotonic() + 1200, 0
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise RuntimeError("Remote archive download timed out")
                        block = os.read(process.stdout.fileno(), 1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if max_bytes is not None and total > max_bytes:
                            raise ValueError("Downloaded archive exceeds the configured disk limit")
                        output.write(block)
                if process.wait(timeout=max(1, deadline - time.monotonic())):
                    raise RuntimeError("Remote archive download failed")
            except BaseException:
                process.kill()
                process.wait()
                raise


def write_local_status(destination, report):
    destination = private_directory(destination)
    fd, temporary = tempfile.mkstemp(prefix=".status-", dir=destination)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(report, output, indent=2)
        os.replace(temporary, destination / ".last-pull.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def pull(destination=DEFAULT_DESTINATION, max_bytes=None):
    destination = private_directory(destination)
    lock_fd = os.open(destination / ".pull.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = ssh_run(
            "docker exec -i emviary python -", input=REMOTE_SELECT.encode(), stdout=subprocess.PIPE
        )
        try:
            metadata = json.loads(selected.stdout)
            name, digest = metadata["name"], metadata["manifest_sha256"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", name):
                raise ValueError
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise ValueError("Remote backup metadata is invalid") from None
        with tempfile.TemporaryDirectory(prefix=".download-", dir=destination) as temporary:
            archive = Path(temporary) / "backup.tar"
            command = "tar -C " + shlex.quote(REMOTE_ROOT + "/" + name) + " -cf - ."
            download_archive(command, archive, max_bytes)
            report = publish_archive(archive, destination, name, digest, max_bytes)
        # Do not put status files inside the integrity-checked backup itself.
        report["checked_at"] = datetime.now(UTC).isoformat()
        remote_status = {
            "created_at": report["checked_at"],
            "backup_name": name,
            "manifest_sha256": digest,
            "restore_rehearsal": "passed",
        }
        update = (
            "import json,os,tempfile\n"
            "from pathlib import Path\n"
            "root=Path('/data')\n"
            "fd,name=tempfile.mkstemp(prefix='.offhost-',dir=root)\n"
            "os.fchmod(fd,0o600)\n"
            "with os.fdopen(fd,'w') as output:\n"
            "    json.dump(" + repr(remote_status) + ",output)\n"
            "os.replace(name,root/'offhost-backup.json')\n"
        )
        ssh_run("docker exec -i emviary python -", input=update.encode(), stdout=subprocess.PIPE)
        write_local_status(destination, report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--max-bytes", type=int, help="Optional maximum archive/payload size")
    args = parser.parse_args()
    if args.max_bytes is not None and args.max_bytes <= 0:
        parser.error("--max-bytes must be positive")
    os.umask(0o077)
    try:
        print(json.dumps(pull(args.destination, args.max_bytes), indent=2))
    except (OSError, ValueError, RuntimeError, tarfile.TarError, subprocess.TimeoutExpired):
        try:
            write_local_status(
                args.destination, {"status": "failed", "checked_at": datetime.now(UTC).isoformat()}
            )
        except (OSError, ValueError):
            pass
        parser.exit(1, "Verified backup pull failed; no existing backup was replaced.\n")


if __name__ == "__main__":
    main()
