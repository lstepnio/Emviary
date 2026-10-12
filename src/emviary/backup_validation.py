"""Backup integrity and isolated, offline restore rehearsals."""

import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path, PurePosixPath

from PIL import Image

from .render import validate_epdgz

MANIFEST = "integrity-manifest.json"


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Backup must be a regular directory")
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Backup contains a symbolic link")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
        elif not path.is_dir():
            raise ValueError("Backup contains an unsupported filesystem entry")
    return files


def write_manifest(root):
    root = Path(root)
    files = safe_files(root)
    records = {
        name: {"size": path.stat().st_size, "sha256": file_digest(path)}
        for name, path in sorted(files.items())
        if name not in {MANIFEST, "COMPLETE"}
    }
    (root / MANIFEST).write_text(json.dumps({"version": 1, "files": records}, indent=2) + "\n")


class OfflineRestoreProviders:
    def inputs(self, *args, **kwargs):
        raise RuntimeError("Network providers are disabled during restore rehearsal")


def unavailable_converter(*args, **kwargs):
    raise RuntimeError("Image preparation is disabled during restore rehearsal")


def verify_backup(root, *, require_complete=True, temp_dir=None):
    """Validate every payload file, then restore only a clone. Never contact a provider."""
    from .service import Service
    from .settings import Settings

    root = Path(root).absolute()
    files = safe_files(root)
    if MANIFEST not in files:
        raise ValueError("Backup has no integrity manifest; legacy backups need manual validation")
    if require_complete and "COMPLETE" not in files:
        raise ValueError("Backup is incomplete")
    try:
        manifest = json.loads(files[MANIFEST].read_text())
        records = manifest["files"]
        if manifest["version"] != 1 or not isinstance(records, dict):
            raise ValueError
        payload = set(files) - {MANIFEST, "COMPLETE"}
        if payload != set(records):
            raise ValueError
        for name, record in records.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
                raise ValueError
            path = files[name]
            if (
                type(record["size"]) is not int
                or record["size"] != path.stat().st_size
                or record["sha256"] != file_digest(path)
            ):
                raise ValueError
        if require_complete:
            marker = json.loads(files["COMPLETE"].read_text())
            if marker["manifest_sha256"] != file_digest(files[MANIFEST]):
                raise ValueError
    except (KeyError, TypeError, json.JSONDecodeError, ValueError):
        raise ValueError("Backup integrity manifest or file checks failed") from None
    if any(name.startswith("emviary.sqlite3-") for name in files):
        raise ValueError("Backup database must not depend on WAL or journal sidecars")
    required = {"emviary.sqlite3", "site.json", "art/catalog.json", "event-art/manifest.json"}
    if not required <= set(files):
        raise ValueError("Backup is missing required restore files")
    try:
        with sqlite3.connect(
            files["emviary.sqlite3"].as_uri() + "?mode=ro&immutable=1", uri=True
        ) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Backup database failed integrity validation")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Backup database has invalid references")
            db.row_factory = sqlite3.Row
            original_frames = [dict(r) for r in db.execute("SELECT * FROM frames ORDER BY id")]
            images = [dict(r) for r in db.execute("SELECT * FROM images")]
            slots = [dict(r) for r in db.execute("SELECT * FROM prepared_slots")]
    except sqlite3.Error:
        raise ValueError("Backup database cannot be read or has invalid schema") from None
    try:
        with tempfile.TemporaryDirectory(
            prefix=".emviary-restore-", dir=Path(temp_dir) if temp_dir else root.parent
        ) as temporary:
            clone = Path(temporary)
            data = clone / "data"
            data.mkdir()
            shutil.copy2(files["emviary.sqlite3"], data / "emviary.sqlite3")
            shutil.copy2(files["site.json"], clone / "site.json")
            shutil.copytree(root / "art", clone / "art")
            shutil.copytree(root / "event-art", data / "event-art")
            shutil.copytree(root / "active-cache", data / "cache")
            restored = Service(
                Settings(
                    config_path=clone / "site.json",
                    data_dir=data,
                    art_dir=clone / "art",
                    backup_dir=clone / "backups",
                ),
                providers=OfflineRestoreProviders(),
                converter=unavailable_converter,
            )
            for entry in restored.event_art.entries():
                asset = restored.event_art.path(entry)
                if not asset.is_file() or file_digest(asset) != entry.get("asset_sha256"):
                    raise ValueError("Backup event artwork is missing or invalid")
            if restored.store.frames() != original_frames:
                raise ValueError("Restored frame registry differs from backup")
            image_by_id = {r["id"]: r for r in images}
            mandatory = {r["id"] for r in images if not r.get("hidden", 0)}
            mandatory.update(s["image_id"] for s in slots if s["image_id"] is not None)
            delivered_count = 0
            for frame in restored.store.frames():
                for key in ("active_image_id", "max_delivered_image_id"):
                    if frame.get(key) is not None:
                        mandatory.add(frame[key])
                delivered = restored.delivered_image(frame)
                if frame.get("last_served_etag") and delivered is None:
                    raise ValueError("Last-delivered image reference is missing")
                if delivered:
                    mandatory.add(delivered["id"])
                    delivered_count += 1
                active = restored.store.active_image(frame)
                if frame.get("active_image_id") and active is None:
                    raise ValueError("Active image reference is unavailable")
            for identifier in mandatory:
                image = image_by_id.get(identifier)
                if image is None:
                    raise ValueError("Restored image reference is missing")
                plan = json.loads(image["manifest"])
                for artwork in plan.get("artworks", [plan["artwork"]]):
                    art_root = (
                        restored.event_art.root
                        if artwork.get("event_only")
                        else restored.settings.art_dir
                    )
                    asset = art_root / artwork["asset"]
                    if (
                        not asset.resolve().is_relative_to(art_root.resolve())
                        or not asset.is_file()
                        or file_digest(asset) != artwork.get("asset_sha256")
                    ):
                        raise ValueError("Backup retained artwork asset is missing or invalid")
                path = restored.cache_path(image["path"])
                preview = restored.cache_path(image["preview_path"])
                if not path.is_file() or not preview.is_file():
                    raise ValueError("Backup is missing a retained image or preview")
                if validate_epdgz(path) != image["body_hash"]:
                    raise ValueError("Restored image bytes differ from database digest")
                with Image.open(preview) as picture:
                    picture.verify()
            # Exercise cursor navigation using existing bytes, without preparing new artwork.
            for frame in restored.store.frames():
                for image in images:
                    if image["frame_id"] == frame["id"] and image["id"] in mandatory:
                        for direction in ("previous", "next"):
                            navigated = restored.store.navigation_image(
                                frame, direction, image["body_hash"]
                            )
                            if navigated and navigated["id"] not in mandatory:
                                raise ValueError("Navigation selected an unvalidated image")
            return {
                "status": "verified",
                "files": len(records),
                "frames": len(original_frames),
                "artworks": len(restored.settings.artworks),
                "special_day_artworks": len(restored.event_art.entries()),
                "retained_images": len(mandatory),
                "delivered_images": delivered_count,
                "restore_rehearsal": "passed",
                "network_providers": "disabled",
            }
    except (OSError, sqlite3.Error, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(
            ("Restored", "Backup", "Last-", "Active", "Navigation")
        ):
            raise
        raise ValueError("Isolated restore rehearsal failed") from None
