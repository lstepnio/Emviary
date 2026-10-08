import fcntl
import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import render
from .providers import Providers
from .settings import Config, FramePolicy, Settings
from .store import Store, stable_json, utcnow

log = logging.getLogger(__name__)


@contextmanager
def preparation_lock(data_dir):
    with (data_dir / "prepare.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another preparation or backup is already running") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Service:
    def __init__(self, settings=None, providers=None, converter=None):
        self.settings = settings or Settings()
        self.store = Store(self.settings.db_path)
        with self.store.connect() as db:
            override = db.execute("SELECT value FROM config_overrides WHERE id=1").fetchone()
        if override:
            self.settings.config = Config.model_validate_json(override["value"])
        self.providers = providers or Providers(self.store)
        self.converter = converter or render.convert

    def save_configuration(self, value):
        config = Config.model_validate(value)
        with preparation_lock(self.settings.data_dir):
            for frame in self.store.frames():
                config.site(frame["site_id"])
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO config_overrides(id,value) VALUES(1,?) "
                    "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                    (config.model_dump_json(),),
                )
            self.settings.config = config

    def delivered_image(self, frame):
        tag = frame.get("last_served_etag") or ""
        digest = tag.strip('"').split("-c")[0]
        with self.store.connect() as db:
            image = db.execute(
                "SELECT * FROM images WHERE frame_id=? AND body_hash=? ORDER BY id DESC LIMIT 1",
                (frame["id"], digest),
            ).fetchone()
        return dict(image) if image else None

    def cache_path(self, name):
        path = (self.settings.data_dir / name).resolve()
        if not path.is_relative_to(self.settings.data_dir / "cache"):
            raise ValueError("Cache file is outside the configured cache directory")
        return path

    def _new_plan(self, frame, local_date, revision, profile, offline):
        policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
        policy.pop("wifi_networks", None)
        policy.pop("wifi_forget_ssids", None)
        site = self.settings.config.site(frame["site_id"])
        inputs = self.providers.inputs(site, local_date, offline=offline)
        cutoff = (
            date.fromisoformat(local_date) - timedelta(days=policy["repeat_penalty_days"])
        ).isoformat()
        with self.store.connect() as db:
            manifests = [
                json.loads(r["manifest"])
                for r in db.execute(
                    """SELECT manifest FROM images WHERE frame_id=?
                       AND local_date>=? AND local_date<?""",
                    (frame["id"], cutoff, local_date),
                )
            ]
        recent = [
            a["scientific_name"] for m in manifests for a in m.get("artworks", [m["artwork"]])
        ]
        seed = hashlib.sha256(
            f"{frame['id']}:{local_date}:{revision}:{profile}".encode()
        ).hexdigest()
        candidates = self.settings.artworks
        if policy["allowed_species"]:
            candidates = [
                a for a in candidates if a["scientific_name"] in policy["allowed_species"]
            ]
        occasion = render.special_day_for(policy, local_date)
        if occasion:
            requested = next(
                (
                    a
                    for a in self.settings.artworks
                    if a["id"] == occasion["artwork_id"]
                    and a["approved"]
                    and int(local_date[5:7]) in a["months"]
                    and a.get("depicted_birds", 1) == 1
                ),
                None,
            )
            artworks = [
                requested
                or render.choose_art(
                    [a for a in candidates if a.get("depicted_birds", 1) == 1],
                    local_date,
                    inputs,
                    recent,
                    seed + ":occasion",
                )
            ]
        else:
            artworks = render.choose_artworks(candidates, local_date, inputs, recent, seed, policy)
        return {
            "frame_id": frame["id"],
            "location_label": "COLORADO" if site.bird_area == "colorado" else "DENVER",
            "local_date": local_date,
            "revision": revision,
            "profile_hash": profile,
            "policy": policy,
            "inputs": inputs,
            "seed": seed,
            "artwork": artworks[0],
            "artworks": artworks,
            "special_day": occasion,
            "layout": {
                "bird_count": sum(a.get("depicted_birds", 1) for a in artworks),
                "panel_capacity": 3,
            },
            "license": render.composition_license(artworks),
            "artwork_licenses": sorted({a["license"] for a in artworks}),
            "renderer_version": render.RENDER_VERSION,
            "converter_version": self.settings.config.render.initial_converter_version,
        }

    def preview_special_day(self, frame_id, day_id):
        frame = self.store.frame(frame_id)
        policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
        occasion = next((d for d in policy["special_days"] if d["id"] == day_id), None)
        if not occasion:
            raise ValueError("Unknown special day")
        site = self.settings.config.site(frame["site_id"])
        today = datetime.now(ZoneInfo(site.timezone)).date()
        preview_date = date.fromisoformat(occasion["date"])
        if occasion["annual"]:
            month, day = preview_date.month, preview_date.day
            for year in range(today.year, today.year + 9):
                try:
                    candidate = date(year, month, day)
                except ValueError:
                    continue
                if candidate >= today:
                    preview_date = candidate
                    break
        candidates = [
            a
            for a in self.settings.artworks
            if a["approved"]
            and preview_date.month in a["months"]
            and a.get("depicted_birds", 1) == 1
        ]
        requested = next((a for a in candidates if a["id"] == occasion["artwork_id"]), None)
        if not requested and policy["allowed_species"]:
            candidates = [
                a for a in candidates if a["scientific_name"] in policy["allowed_species"]
            ]
        artwork = requested or render.choose_art(
            candidates, preview_date.isoformat(), {}, [], day_id
        )
        plan = {
            "local_date": preview_date.isoformat(),
            "inputs": {},
            "policy": policy,
            "artworks": [artwork],
            "special_day": occasion,
        }
        with preparation_lock(self.settings.data_dir), tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            master, packed, preview = (
                root / "master.png",
                root / "panel.epdgz",
                root / "preview.jpg",
            )
            render.compose(self.settings.art_dir, artwork, plan, master)
            self.converter(
                master, packed, preview, policy, self.settings.config.render.timeout_seconds
            )
            render.validate_epdgz(packed)
            return preview.read_bytes()

    def prepare(self, frame_id, local_date=None, force=False, offline=False):
        with preparation_lock(self.settings.data_dir):
            return self._prepare(frame_id, local_date, force, offline)

    def _prepare(self, frame_id, local_date, force, offline):
        frame = self.store.frame(frame_id)
        policy = FramePolicy.model_validate_json(frame["policy"])
        site = self.settings.config.site(frame["site_id"])
        local_date = local_date or datetime.now(ZoneInfo(site.timezone)).date().isoformat()
        date.fromisoformat(local_date)
        profile = render.profile_hash(policy.model_dump(), self.settings.catalog)
        profile = hashlib.sha256((profile + stable_json(site.model_dump())).encode()).hexdigest()
        with self.store.connect() as db:
            job = db.execute(
                """SELECT * FROM jobs WHERE frame_id=? AND local_date=? AND profile_hash=?
                   ORDER BY revision DESC LIMIT 1""",
                (frame_id, local_date, profile),
            ).fetchone()
            if job and not force:
                plan = json.loads(job["plan"])
                image = db.execute(
                    "SELECT * FROM images WHERE frame_id=? AND local_date=? AND revision=?",
                    (frame_id, local_date, job["revision"]),
                ).fetchone()
                if image:
                    cached = self.cache_path(image["path"])
                    if (
                        cached.is_file()
                        and hashlib.sha256(cached.read_bytes()).hexdigest() == image["body_hash"]
                    ):
                        return dict(image)
            else:
                row = db.execute(
                    "SELECT MAX(revision) FROM jobs WHERE frame_id=? AND local_date=?",
                    (frame_id, local_date),
                ).fetchone()
                revision = (row[0] or 0) + 1
                plan = None
        if plan is None:
            plan = self._new_plan(frame, local_date, revision, profile, offline)
            with self.store.connect() as db:
                db.execute(
                    """INSERT INTO jobs(frame_id,local_date,revision,profile_hash,plan,status)
                       VALUES(?,?,?,?,?,'pending')""",
                    (frame_id, local_date, revision, profile, stable_json(plan)),
                )
        revision = plan["revision"]
        key = (frame_id, local_date, revision)
        with self.store.connect() as db:
            db.execute(
                """UPDATE jobs SET status='running',attempts=attempts+1,started_at=?,
                   finished_at=NULL,error=NULL WHERE frame_id=? AND local_date=? AND revision=?""",
                (utcnow(), *key),
            )
        try:
            with tempfile.TemporaryDirectory(
                prefix="prepare-", dir=self.settings.data_dir / "cache"
            ) as tmp:
                tmp = Path(tmp)
                master, packed, preview = (
                    tmp / "master.png",
                    tmp / "image.epdgz",
                    tmp / "preview.jpg",
                )
                render.compose(self.settings.art_dir, plan["artwork"], plan, master)
                self.converter(
                    master,
                    packed,
                    preview,
                    plan["policy"],
                    self.settings.config.render.timeout_seconds,
                )
                body_hash = render.validate_epdgz(packed)
                with render.Image.open(preview) as image:
                    image.verify()
                # Immutable unique names leave the old manifest and bytes intact on failure.
                stem = f"{frame_id}-{local_date}-r{revision}-{body_hash[:16]}"
                path = f"cache/{stem}.epdgz"
                preview_path = f"cache/{stem}.jpg"
                packed.replace(self.cache_path(path))
                preview.replace(self.cache_path(preview_path))
                master.replace(self.cache_path(f"cache/{stem}-master.png"))
            with self.store.connect() as db:
                db.execute(
                    """INSERT INTO images(frame_id,local_date,revision,profile_hash,artwork_id,
                       path,preview_path,body_hash,manifest,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(frame_id,local_date,revision) DO UPDATE SET
                       path=excluded.path,preview_path=excluded.preview_path,
                       body_hash=excluded.body_hash,manifest=excluded.manifest""",
                    (
                        frame_id,
                        local_date,
                        revision,
                        profile,
                        plan["artwork"]["id"],
                        path,
                        preview_path,
                        body_hash,
                        stable_json(plan),
                        utcnow(),
                    ),
                )
                image_id = db.execute(
                    "SELECT id FROM images WHERE frame_id=? AND local_date=? AND revision=?", key
                ).fetchone()[0]
                db.execute("UPDATE frames SET active_image_id=? WHERE id=?", (image_id, frame_id))
                db.execute(
                    """UPDATE jobs SET status='done',finished_at=?,error=NULL
                       WHERE frame_id=? AND local_date=? AND revision=?""",
                    (utcnow(), *key),
                )
            log.info("Prepared frame=%s date=%s revision=%s", frame_id, local_date, revision)
            return self.store.active_image(self.store.frame(frame_id))
        except Exception as exc:
            with self.store.connect() as db:
                db.execute(
                    """UPDATE jobs SET status='failed',finished_at=?,error=?
                       WHERE frame_id=? AND local_date=? AND revision=?""",
                    (utcnow(), type(exc).__name__, *key),
                )
            raise

    def prepare_due(self, now=None):
        now = now or datetime.now(UTC)
        with preparation_lock(self.settings.data_dir):
            for frame in self.store.frames():
                site = self.settings.config.site(frame["site_id"])
                local = now.astimezone(ZoneInfo(site.timezone))
                local_date = local.date().isoformat()
                image = self.store.active_image(frame)
                if image and local.strftime("%H:%M") < site.prepare_local_time:
                    continue
                # Retry failed preparation every 15 minutes, with at most three attempts/day.
                with self.store.connect() as db:
                    failed = db.execute(
                        """SELECT * FROM jobs WHERE frame_id=? AND local_date=?
                           ORDER BY revision DESC LIMIT 1""",
                        (frame["id"], local_date),
                    ).fetchone()
                if failed and failed["status"] == "failed":
                    if failed["attempts"] >= 3:
                        continue
                    if datetime.fromisoformat(failed["finished_at"]) > now - timedelta(minutes=15):
                        continue
                try:
                    self._prepare(frame["id"], local_date, force=False, offline=False)
                except Exception as exc:
                    log.error(
                        "Preparation failed frame=%s error=%s", frame["id"], type(exc).__name__
                    )
            for site in self.settings.config.sites:
                local = now.astimezone(ZoneInfo(site.timezone))
                if local.strftime("%H:%M") >= "03:00":
                    directory = self.settings.backup_dir / local.date().isoformat()
                    if not (directory / "COMPLETE").is_file():
                        self._backup(directory)
                        self._prune_backups()
                        self._prune_history(local.date())

    def _prune_history(self, today):
        cutoff = (today - timedelta(days=30)).isoformat()
        with self.store.connect() as db:
            expired = db.execute(
                """SELECT * FROM images WHERE local_date<? AND id NOT IN
                   (SELECT active_image_id FROM frames WHERE active_image_id IS NOT NULL)
                   AND NOT EXISTS (SELECT 1 FROM frames WHERE frames.id=images.frame_id AND
                       images.body_hash=substr(trim(frames.last_served_etag,'"'),1,64))""",
                (cutoff,),
            ).fetchall()
            for image in expired:
                db.execute("DELETE FROM images WHERE id=?", (image["id"],))
            db.execute(
                """DELETE FROM jobs WHERE local_date<? AND NOT EXISTS
                   (SELECT 1 FROM images WHERE images.frame_id=jobs.frame_id
                    AND images.local_date=jobs.local_date AND images.revision=jobs.revision)""",
                (cutoff,),
            )
            db.execute(
                "DELETE FROM provider_snapshots WHERE local_date<?",
                ((today - timedelta(days=14)).isoformat(),),
            )
        # Remove files after committing rows. Interrupted cleanup leaves harmless orphan files.
        for image in expired:
            for name in (image["path"], image["preview_path"]):
                self.cache_path(name).unlink(missing_ok=True)
            master_name = str(Path(image["path"]).with_suffix("")) + "-master.png"
            self.cache_path(master_name).unlink(missing_ok=True)

    def _backup(self, output):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        database = output / "emviary.sqlite3"
        with self.store.connect() as source:
            destination = sqlite3.connect(database)
            try:
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Backup database failed integrity validation")
            finally:
                destination.close()
        (output / "site.json").write_text(self.settings.config.model_dump_json(indent=2))
        shutil.copytree(self.settings.art_dir, output / "art", dirs_exist_ok=True)
        # Cache images are rebuildable but the active last-good image is useful for recovery.
        cache = output / "active-cache"
        cache.mkdir(exist_ok=True)
        for frame in self.store.frames():
            for image in (self.store.active_image(frame), self.delivered_image(frame)):
                if not image:
                    continue
                for name in (image["path"], image["preview_path"]):
                    shutil.copy2(self.cache_path(name), cache / Path(name).name)
        (output / "COMPLETE").write_text(utcnow())
        return str(output)

    def backup(self, output=None):
        output = output or self.settings.backup_dir / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        with preparation_lock(self.settings.data_dir):
            return self._backup(output)

    def _prune_backups(self):
        daily = sorted(
            p
            for p in self.settings.backup_dir.iterdir()
            if p.is_dir() and len(p.name) == 10 and (p / "COMPLETE").exists()
        )
        for path in daily[:-7]:
            shutil.rmtree(path)

    def status(self):
        result = []
        now = datetime.now(UTC)
        with self.store.connect() as db:
            for frame in self.store.frames():
                image = self.store.active_image(frame)
                contact = frame["last_contact"]
                age = (now - datetime.fromisoformat(contact)).total_seconds() if contact else None
                job = db.execute(
                    "SELECT status,error,attempts FROM jobs WHERE frame_id=? ORDER BY "
                    "local_date DESC,revision DESC LIMIT 1",
                    (frame["id"],),
                ).fetchone()
                result.append(
                    {
                        "id": frame["id"],
                        "site_id": frame["site_id"],
                        "config_revision": frame["config_revision"],
                        "wake_local_time": json.loads(frame["policy"])["wake_local_time"],
                        "last_contact": contact,
                        "contact_overdue": age is not None and age > 129600,
                        "battery": frame["battery"],
                        "firmware": frame["firmware"],
                        "client_etag": frame["last_client_etag"],
                        "served_etag": frame["last_served_etag"],
                        "image_date": image["local_date"] if image else None,
                        "artwork_id": image["artwork_id"] if image else None,
                        "last_job": dict(job) if job else None,
                    }
                )
        return result
