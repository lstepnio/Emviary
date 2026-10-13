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
from .event_art import EventArt
from .providers import Providers
from .settings import Config, FramePolicy, Settings
from .store import RevisionConflict, Store, stable_json, utcnow

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
    def __init__(self, settings=None, providers=None, converter=None, clock=None):
        self.clock = clock or (lambda: datetime.now(UTC))
        self.settings = settings or Settings()
        self.store = Store(self.settings.db_path)
        self.event_art = EventArt(self.settings.data_dir)
        with preparation_lock(self.settings.data_dir):
            self.event_art.approve_existing()
        # Keep the read-only source catalog as recovery data, while the active
        # catalog excludes persistent owner deletions in SQLite.
        if not hasattr(self.settings, "source_catalog"):
            self.settings.source_catalog = self.settings.catalog
        self.refresh_artwork_library()

        with self.store.connect() as db:
            override = db.execute("SELECT value FROM config_overrides WHERE id=1").fetchone()
        if override:
            self.settings.config = Config.model_validate_json(override["value"])
        self.providers = providers or Providers(self.store)
        self.converter = converter or render.convert

    def refresh_artwork_library(self):
        with self.store.connect() as db:
            deleted = {r[0] for r in db.execute("SELECT id FROM deleted_artworks")}
        self.settings.artworks = [
            a for a in self.settings.source_catalog["artworks"] if a["id"] not in deleted
        ]
        self.settings.catalog = {**self.settings.source_catalog, "artworks": self.settings.artworks}

    def deleted_artwork_entries(self):
        active = {a["id"] for a in self.settings.artworks}
        return [a for a in self.settings.source_catalog["artworks"] if a["id"] not in active]

    def delete_artworks(self, identifiers):
        identifiers = set(identifiers)
        with preparation_lock(self.settings.data_dir):
            active = {a["id"] for a in self.settings.artworks}
            if not identifiers <= active:
                raise ValueError("Unknown artwork")
            excluded = self.store.excluded_artworks()
            if identifiers and not any(
                a["approved"] and a["id"] not in identifiers | excluded
                for a in self.settings.artworks
            ):
                raise ValueError("Keep at least one artwork in rotation")
            with self.store.connect() as db:
                db.executemany(
                    "INSERT OR IGNORE INTO deleted_artworks VALUES(?,?)",
                    [(identifier, datetime.now(UTC).isoformat()) for identifier in identifiers],
                )
            self.refresh_artwork_library()
            for frame in self.store.frames():
                image = self.store.active_image(frame)
                if image:
                    plan = json.loads(image["manifest"])
                    if any(a["id"] in identifiers for a in plan.get("artworks", [plan["artwork"]])):
                        self.store.request_refill(frame["id"], image["id"])
        return len(identifiers)

    def restore_artwork(self, identifier):
        with preparation_lock(self.settings.data_dir):
            if not any(a["id"] == identifier for a in self.deleted_artwork_entries()):
                raise ValueError("Unknown deleted artwork")
            with self.store.connect() as db:
                db.execute("DELETE FROM deleted_artworks WHERE id=?", (identifier,))
            self.refresh_artwork_library()

    def settings_revision(self):
        return hashlib.sha256(stable_json(self.settings.config.model_dump()).encode()).hexdigest()

    def save_configuration(self, value, expected_revision=None):
        config = Config.model_validate(value)
        with preparation_lock(self.settings.data_dir):
            if expected_revision is not None and expected_revision != self.settings_revision():
                raise RevisionConflict("Connections changed in another tab. Reload before saving.")
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

    def configuration_hash(self, frame):
        policy = FramePolicy.model_validate_json(frame["policy"])
        site = self.settings.config.site(frame["site_id"])
        return hashlib.sha256(
            (
                render.profile_hash(policy.model_dump(), self.settings.catalog)
                + stable_json(site.model_dump())
                + stable_json(sorted(self.store.excluded_artworks()))
                + stable_json(self.event_art.entries())
            ).encode()
        ).hexdigest()

    def image_usable(self, image, frame, now=None, fresh=True):
        if not image or image.get("hidden"):
            return False
        now = now or self.clock()
        site = self.settings.config.site(frame["site_id"])
        if image["local_date"] != now.astimezone(ZoneInfo(site.timezone)).date().isoformat():
            return False
        plan = json.loads(image["manifest"])
        if plan.get("configuration_hash", image["profile_hash"]) != self.configuration_hash(frame):
            return False
        policy = FramePolicy.model_validate_json(frame["policy"])
        if not policy.weather_cues or not site.providers.open_meteo.enabled:
            return True
        forecast = plan["inputs"].get("open_meteo")
        if not forecast:
            # A weather-free image remains an honest fallback for its own day.
            stamp = plan.get("prepared_at", image["created_at"])
            return not fresh or now - datetime.fromisoformat(stamp) < timedelta(
                minutes=policy.weather_max_age_minutes
            )
        if forecast.get("local_date") != image["local_date"] or not forecast.get("fetched_at"):
            return False
        stamp = datetime.fromisoformat(forecast["fetched_at"])
        return stamp <= now + timedelta(minutes=5) and now - stamp < timedelta(
            minutes=policy.weather_max_age_minutes
        )

    def request_navigation_refresh(self, frame):
        self.store.request_refill(frame["id"], frame["active_image_id"] or 0)

    def select_image(self, frame, direction, client_tag, now=None):
        """Only database/cache selection on the wake path; never fetch or render here."""
        now = now or self.clock()
        navigation = self.store.slot_image(frame["id"], "navigation")
        scheduled = self.store.slot_image(frame["id"], "scheduled")
        digest = client_tag.removeprefix("W/").strip('"').split("-c")[0]
        with self.store.connect() as db:
            cursor = db.execute(
                "SELECT * FROM images WHERE frame_id=? AND body_hash=? ORDER BY id DESC LIMIT 1",
                (frame["id"], digest),
            ).fetchone()
            cursor = dict(cursor) if cursor else None
        if direction == "previous" and cursor:
            candidate = self.store.navigation_image(frame, direction, client_tag)
            if candidate and (
                candidate["id"] <= cursor["id"] or self.image_usable(candidate, frame, now)
            ):
                return candidate, False
        if direction == "next" and cursor and frame.get("max_delivered_image_id"):
            candidate = self.store.navigation_image(frame, direction, client_tag)
            if candidate and cursor["id"] < candidate["id"] <= frame["max_delivered_image_id"]:
                return candidate, False
        # An explicitly requested occasion preview takes priority until delivered.
        if (
            navigation
            and (
                json.loads(navigation["manifest"]).get("special_day_test")
                or json.loads(navigation["manifest"]).get("appearance_preview")
            )
            and self.image_usable(navigation, frame, now)
        ):
            return navigation, False
        choices = [scheduled, navigation] if direction == "latest" else [navigation]
        for image in choices:
            if self.image_usable(image, frame, now):
                return image, False
        self.request_navigation_refresh(frame)
        # Do not mislabel an expired forecast as fresh. Prefer a weather-free
        # same-day fallback, otherwise retain the device's existing bytes (304).
        for image in choices:
            if self.image_usable(image, frame, now, fresh=False):
                return image, False
        if cursor and not cursor.get("hidden"):
            return cursor, True
        return None, False

    def _new_plan(
        self,
        frame,
        local_date,
        revision,
        profile,
        offline,
        special_day_id=None,
        now=None,
        weather_not_before=None,
    ):
        policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
        policy.pop("wifi_networks", None)
        policy.pop("wifi_forget_ssids", None)
        site = self.settings.config.site(frame["site_id"])
        inputs = self.providers.inputs(
            site,
            local_date,
            offline=offline,
            now=now or self.clock(),
            weather_max_age_minutes=policy["weather_max_age_minutes"],
            weather_not_before=weather_not_before,
        )
        cutoff = (
            date.fromisoformat(local_date) - timedelta(days=policy["repeat_penalty_days"])
        ).isoformat()
        with self.store.connect() as db:
            manifests = [
                json.loads(r["manifest"])
                for r in db.execute(
                    """SELECT manifest FROM images WHERE frame_id=?
                       AND local_date>=? AND local_date<=?
                       ORDER BY local_date DESC, revision DESC LIMIT 21""",
                    (frame["id"], cutoff, local_date),
                )
            ]
        recent = [
            a["scientific_name"]
            for m in manifests
            for a in m.get("artworks", [m["artwork"]])
            if not a.get("event_only")
        ]
        seed = hashlib.sha256(
            f"{frame['id']}:{local_date}:{revision}:{profile}".encode()
        ).hexdigest()
        excluded = self.store.excluded_artworks()
        candidates = [a for a in self.settings.artworks if a["id"] not in excluded]
        if policy["allowed_species"]:
            candidates = [
                a for a in candidates if a["scientific_name"] in policy["allowed_species"]
            ]
        occasion = render.special_day_for(policy, local_date)
        if special_day_id is not None:
            occasion = next((d for d in policy["special_days"] if d["id"] == special_day_id), None)
            if occasion is None:
                raise ValueError("Unknown special day")
        if occasion:
            requested = next(
                (
                    a
                    for a in candidates
                    if a["id"] == occasion["artwork_id"]
                    and a["approved"]
                    and int(local_date[5:7]) in a["months"]
                    and a.get("depicted_birds", 1) == 1
                ),
                None,
            )
            requested = next(
                (
                    a
                    for a in self.event_art.entries()
                    if a["id"] == occasion["artwork_id"] and a["approved"]
                ),
                requested,
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
            artworks = render.choose_artworks(
                candidates, local_date, inputs, recent, seed, policy, manifests
            )
        return {
            "frame_id": frame["id"],
            "configuration_hash": self.configuration_hash(frame),
            "prepared_at": (now or self.clock()).isoformat(),
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
            "special_day_test": special_day_id is not None,
            "layout": {
                "name": "occasion"
                if occasion
                else render.choose_layout(artworks, seed, manifests, self.settings.art_dir),
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
        site = self.settings.config.site(frame["site_id"])
        today = self.clock().astimezone(ZoneInfo(site.timezone)).date().isoformat()
        plan = self._new_plan(frame, today, 0, "preview", False, day_id)
        artwork, policy = plan["artwork"], plan["policy"]
        with preparation_lock(self.settings.data_dir), tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            master, packed, preview = (
                root / "master.png",
                root / "panel.epdgz",
                root / "preview.jpg",
            )
            render.compose(self.settings.art_dir, artwork, plan, master, self.event_art.root)
            self.converter(
                master, packed, preview, policy, self.settings.config.render.timeout_seconds
            )
            render.validate_epdgz(packed)
            return preview.read_bytes()

    def preview_appearance(self, frame_id, policy):
        """Render draft settings without saving a policy or consuming rotation."""
        policy = FramePolicy.model_validate(policy)
        with preparation_lock(self.settings.data_dir):
            frame = self.store.frame(frame_id)
            draft_frame = {**frame, "policy": policy.model_dump_json(), "site_id": policy.site_id}
            today = (
                self.clock()
                .astimezone(ZoneInfo(self.settings.config.site(policy.site_id).timezone))
                .date()
                .isoformat()
            )
            profile = self.configuration_hash(draft_frame)
            plan = self._new_plan(draft_frame, today, 0, profile, False)
            with tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                master, packed, preview = (
                    root / "master.png",
                    root / "panel.epdgz",
                    root / "preview.jpg",
                )
                render.compose(
                    self.settings.art_dir, plan["artwork"], plan, master, self.event_art.root
                )
                self.converter(
                    master,
                    packed,
                    preview,
                    plan["policy"],
                    self.settings.config.render.timeout_seconds,
                )
                digest = render.validate_epdgz(packed)
                with render.Image.open(preview) as image:
                    image.verify()
                draft = {
                    "frame_id": frame_id,
                    "policy": policy.model_dump(),
                    "plan": plan,
                    "base_hash": self.configuration_hash(frame),
                    "config_revision": frame["config_revision"],
                    "expires": self.clock() + timedelta(minutes=30),
                    "packed": packed.read_bytes(),
                    "preview": preview.read_bytes(),
                    "master": master.read_bytes(),
                    "digest": digest,
                }
            drafts = getattr(self, "_appearance_previews", {})
            drafts = {
                key: value for key, value in drafts.items() if value["expires"] > self.clock()
            }
            while len(drafts) >= 5:
                drafts.pop(next(iter(drafts)))
            import secrets

            token = secrets.token_hex(24)
            drafts[token] = draft
            self._appearance_previews = drafts
            return token

    def appearance_preview(self, frame_id, token):
        draft = getattr(self, "_appearance_previews", {}).get(token)
        if not draft or draft["frame_id"] != frame_id or draft["expires"] <= self.clock():
            raise ValueError("This preview expired. Preview your settings again.")
        return draft

    def queue_appearance_preview(self, frame_id, token, policy):
        """Save reviewed settings and queue the exact reviewed output atomically."""
        policy = FramePolicy.model_validate(policy)
        with preparation_lock(self.settings.data_dir):
            draft = self.appearance_preview(frame_id, token)
            frame = self.store.frame(frame_id)
            if policy.model_dump() != draft["policy"]:
                raise ValueError(
                    "Settings changed after this preview. Preview them again before queuing."
                )
            if (
                frame["config_revision"] != draft["config_revision"]
                or self.configuration_hash(frame) != draft["base_hash"]
            ):
                raise ValueError(
                    "Saved settings changed after this preview. Reload and preview again."
                )
            plan = dict(draft["plan"])
            plan["appearance_preview"] = True
            with self.store.connect() as db:
                revision = db.execute(
                    (
                        "SELECT COALESCE(MAX(revision),0)+1 FROM images WHERE frame_id=? "
                        "AND local_date=?"
                    ),
                    (frame_id, plan["local_date"]),
                ).fetchone()[0]
                plan["revision"] = revision
                stem = f"{frame_id}-{plan['local_date']}-r{revision}-{draft['digest'][:16]}"
                path, preview_path = f"cache/{stem}.epdgz", f"cache/{stem}.jpg"
                self.cache_path(path).write_bytes(draft["packed"])
                self.cache_path(preview_path).write_bytes(draft["preview"])
                self.cache_path(f"cache/{stem}-master.png").write_bytes(draft["master"])
                updated = db.execute(
                    "UPDATE frames SET policy=?,site_id=?,config_revision=config_revision+1 "
                    "WHERE id=? AND config_revision=?",
                    (
                        stable_json(policy.model_dump()),
                        policy.site_id,
                        frame_id,
                        draft["config_revision"],
                    ),
                )
                if not updated.rowcount:
                    raise ValueError(
                        "Saved settings changed after this preview. Reload and preview again."
                    )
                self.store.count_render(db, plan)
                cursor = db.execute(
                    "INSERT INTO images(frame_id,local_date,revision,profile_hash,artwork_id,path,"
                    "preview_path,body_hash,manifest,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        frame_id,
                        plan["local_date"],
                        revision,
                        plan["profile_hash"],
                        plan["artwork"]["id"],
                        path,
                        preview_path,
                        draft["digest"],
                        stable_json(plan),
                        self.clock().isoformat(),
                    ),
                )
                self._publish_slot(db, frame_id, "navigation", cursor.lastrowid, None)
            del self._appearance_previews[token]
            return self.store.active_image(self.store.frame(frame_id))

    def prepare_special_day(self, frame_id, day_id):
        """Queue a test for today without enabling or rescheduling its calendar event."""
        with preparation_lock(self.settings.data_dir):
            return self._prepare(frame_id, None, True, False, day_id)

    def prepare(self, frame_id, local_date=None, force=False, offline=False):
        with preparation_lock(self.settings.data_dir):
            return self._prepare(frame_id, local_date, force, offline)

    def _prepare(
        self,
        frame_id,
        local_date,
        force,
        offline,
        special_day_id=None,
        purpose="navigation",
        cycle=None,
        now=None,
        weather_not_before=None,
        reuse_image=None,
    ):
        frame = self.store.frame(frame_id)
        site = self.settings.config.site(frame["site_id"])
        now = now or self.clock()
        local_date = local_date or now.astimezone(ZoneInfo(site.timezone)).date().isoformat()
        date.fromisoformat(local_date)
        profile = self.configuration_hash(frame)
        if purpose == "scheduled":
            profile = hashlib.sha256((profile + ":scheduled:" + cycle).encode()).hexdigest()
        if special_day_id is not None:
            profile = hashlib.sha256((profile + ":test:" + special_day_id).encode()).hexdigest()
        with self.store.connect() as db:
            job = db.execute(
                """SELECT * FROM jobs WHERE frame_id=? AND local_date=? AND profile_hash=?
                   ORDER BY revision DESC LIMIT 1""",
                (frame_id, local_date, profile),
            ).fetchone()
            image = (
                db.execute(
                    "SELECT * FROM images WHERE frame_id=? AND local_date=? AND revision=?",
                    (frame_id, local_date, job["revision"]),
                ).fetchone()
                if job and not force
                else None
            )
            # A removed image must not satisfy scheduled or retried preparation.
            # Keep its history intact and start a fresh revision instead.
            plan = json.loads(job["plan"]) if job else None
            forecast = (plan or {}).get("inputs", {}).get("open_meteo")
            expired = False
            if forecast:
                stamp = forecast.get("fetched_at")
                expired = (
                    not stamp
                    or datetime.fromisoformat(stamp) > now + timedelta(minutes=5)
                    or datetime.fromisoformat(stamp)
                    <= now
                    - timedelta(
                        minutes=FramePolicy.model_validate_json(
                            frame["policy"]
                        ).weather_max_age_minutes
                    )
                    or (
                        weather_not_before is not None
                        and datetime.fromisoformat(stamp) < weather_not_before
                    )
                )
            if job and not force and not expired and not (image and image["hidden"]):
                if image:
                    cached = self.cache_path(image["path"])
                    if (
                        cached.is_file()
                        and hashlib.sha256(cached.read_bytes()).hexdigest() == image["body_hash"]
                    ):
                        self._publish_slot(db, frame_id, purpose, image["id"], cycle)
                        return dict(image)
            else:
                row = db.execute(
                    "SELECT MAX(revision) FROM jobs WHERE frame_id=? AND local_date=?",
                    (frame_id, local_date),
                ).fetchone()
                revision = (row[0] or 0) + 1
                plan = None
        if plan is None:
            plan = self._new_plan(
                frame,
                local_date,
                revision,
                profile,
                offline,
                special_day_id,
                now=now,
                weather_not_before=weather_not_before,
            )
            if reuse_image and reuse_image["local_date"] == local_date:
                old = json.loads(reuse_image["manifest"])
                if old.get(
                    "configuration_hash", reuse_image["profile_hash"]
                ) == self.configuration_hash(frame):
                    for key in (
                        "artwork",
                        "artworks",
                        "layout",
                        "seed",
                        "license",
                        "artwork_licenses",
                    ):
                        plan[key] = old[key]
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
                render.compose(
                    self.settings.art_dir, plan["artwork"], plan, master, self.event_art.root
                )
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
                existing = db.execute(
                    "SELECT id FROM images WHERE frame_id=? AND local_date=? AND revision=?", key
                ).fetchone()
                if not existing:
                    self.store.count_render(db, plan)
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
                        now.isoformat(),
                    ),
                )
                image_id = db.execute(
                    "SELECT id FROM images WHERE frame_id=? AND local_date=? AND revision=?", key
                ).fetchone()[0]
                self._publish_slot(db, frame_id, purpose, image_id, cycle)
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

    def _publish_slot(self, db, frame_id, purpose, image_id, cycle):
        db.execute(
            "INSERT INTO prepared_slots(frame_id,purpose,image_id,cycle) VALUES(?,?,?,?) "
            "ON CONFLICT(frame_id,purpose) DO UPDATE SET "
            "image_id=excluded.image_id,cycle=excluded.cycle,error=NULL",
            (frame_id, purpose, image_id, cycle),
        )
        if purpose == "scheduled":
            # Share immutable bytes until this image is consumed; no duplicate render.
            db.execute(
                "INSERT INTO prepared_slots(frame_id,purpose,image_id) VALUES(?,'navigation',?) "
                "ON CONFLICT(frame_id,purpose) DO UPDATE SET image_id=excluded.image_id,error=NULL",
                (frame_id, image_id),
            )
        db.execute("UPDATE frames SET active_image_id=? WHERE id=?", (image_id, frame_id))

    def image_delivered(
        self,
        frame_id,
        image_id,
        battery,
        firmware,
        client_tag,
        tag,
        battery_voltage=None,
        battery_charging=None,
        usb_connected=None,
        device_metrics=None,
    ):
        # Called after the HTTP body is sent; preview visits never consume the buffer.
        self.store.telemetry(
            frame_id,
            battery,
            firmware,
            client_tag,
            tag,
            battery_voltage,
            battery_charging,
            usb_connected,
        )
        self.store.device_sample(frame_id, device_metrics, firmware)
        with self.store.connect() as db:
            db.execute(
                "UPDATE frames SET "
                "max_delivered_image_id=MAX(COALESCE(max_delivered_image_id,0),?) WHERE id=?",
                (image_id, frame_id),
            )
        try:
            frame = self.store.frame(frame_id)
        except ValueError:
            return  # The owner removed this frame while its download was in flight.
        if frame["active_image_id"] == image_id:
            self.store.request_refill(frame_id, image_id)
        self.refill_pending(frame_id=frame_id)

    def refill_pending(self, now=None, frame_id=None):
        now = now or self.clock()
        try:
            with preparation_lock(self.settings.data_dir):
                for request in self.store.pending_refills(frame_id):
                    frame = self.store.frame(request["frame_id"])
                    key = (frame["id"], request["consumed_image_id"])
                    if (frame["active_image_id"] or 0) != request["consumed_image_id"]:
                        # A concurrent download or scheduled preparation already refilled it.
                        self.store.complete_refill(*key)
                        continue
                    site = self.settings.config.site(frame["site_id"])
                    local_date = now.astimezone(ZoneInfo(site.timezone)).date().isoformat()
                    current_profile = self.configuration_hash(frame)
                    if request.get("request_profile") != current_profile:
                        with self.store.connect() as db:
                            db.execute(
                                "UPDATE image_refills SET request_profile=?,attempts=0,"
                                "attempt_date=NULL,"
                                "last_attempt_at=NULL WHERE frame_id=? AND consumed_image_id=?",
                                (current_profile, *key),
                            )
                        request = {
                            **request,
                            "attempts": 0,
                            "attempt_date": None,
                            "last_attempt_at": None,
                        }
                    attempts = request["attempts"] if request["attempt_date"] == local_date else 0
                    if attempts >= 3:
                        continue
                    if (
                        attempts
                        and request["last_attempt_at"]
                        and datetime.fromisoformat(request["last_attempt_at"])
                        > now - timedelta(minutes=15)
                    ):
                        continue
                    with self.store.connect() as db:
                        db.execute(
                            """UPDATE image_refills SET attempts=?,attempt_date=?,
                               last_attempt_at=?,error=NULL
                               WHERE frame_id=? AND consumed_image_id=?""",
                            (attempts + 1, local_date, now.isoformat(), *key),
                        )
                    try:
                        candidate = self.store.active_image(frame)
                        reuse = (
                            candidate
                            if candidate
                            and not candidate.get("hidden")
                            and candidate["id"] > (frame.get("max_delivered_image_id") or 0)
                            else None
                        )
                        self._prepare(
                            frame["id"],
                            local_date,
                            force=attempts == 0,
                            offline=False,
                            now=now,
                            reuse_image=reuse,
                        )
                        self.store.complete_refill(*key)
                    except Exception as exc:
                        with self.store.connect() as db:
                            db.execute(
                                """UPDATE image_refills SET error=?
                                   WHERE frame_id=? AND consumed_image_id=?""",
                                (type(exc).__name__, *key),
                            )
                        log.error(
                            "Refill failed frame=%s error=%s", frame["id"], type(exc).__name__
                        )
        except RuntimeError as exc:
            if str(exc) != "Another preparation or backup is already running":
                raise
            # The persistent queue will be picked up by the scheduler on its next tick.
            log.debug("Refill postponed: preparation lock busy")

    def prepare_due(self, now=None):
        now = now or self.clock()
        with preparation_lock(self.settings.data_dir):
            for frame in self.store.frames():
                site = self.settings.config.site(frame["site_id"])
                local = now.astimezone(ZoneInfo(site.timezone))
                today = local.date()
                policy = FramePolicy.model_validate_json(frame["policy"])

                def deadline_for(day):
                    zone = ZoneInfo(site.timezone)
                    wake = (
                        datetime.fromisoformat(day.isoformat() + "T" + policy.wake_local_time)
                        .replace(tzinfo=zone)
                        .astimezone(UTC)
                    )
                    preparation_day = day - timedelta(
                        days=site.prepare_local_time >= policy.wake_local_time
                    )
                    configured = (
                        datetime.fromisoformat(
                            preparation_day.isoformat() + "T" + site.prepare_local_time
                        )
                        .replace(tzinfo=zone)
                        .astimezone(UTC)
                    )
                    recent = wake - timedelta(minutes=min(45, policy.weather_max_age_minutes // 2))
                    # UTC arithmetic also handles a nonexistent spring-forward prep time.
                    return max(configured, recent) if configured < wake else recent

                target = today
                deadline = deadline_for(today)
                tomorrow = today + timedelta(days=1)
                if now >= deadline_for(tomorrow):
                    target = tomorrow
                    deadline = deadline_for(tomorrow)
                cycle = (
                    target.isoformat()
                    + ":"
                    + site.prepare_local_time
                    + ":"
                    + self.configuration_hash(frame)
                )
                state = self.store.slot_state(frame["id"], "scheduled")
                done = (
                    state
                    and state["cycle"] == cycle
                    and self.store.slot_image(frame["id"], "scheduled")
                    and not state["error"]
                )
                eligible = now >= deadline
                attempts = state["attempts"] if state and state["cycle"] == cycle else 0
                retry = not (
                    attempts >= 3
                    or (
                        attempts
                        and state["last_attempt_at"]
                        and datetime.fromisoformat(state["last_attempt_at"])
                        > now - timedelta(minutes=15)
                    )
                )
                if eligible and not done and retry:
                    with self.store.connect() as db:
                        db.execute(
                            "INSERT INTO "
                            "prepared_slots(frame_id,purpose,cycle,attempts,last_attempt_at) "
                            "VALUES(?,'scheduled',?,?,?) ON "
                            "CONFLICT(frame_id,purpose) DO UPDATE SET "
                            "cycle=excluded.cycle,attempts=excluded.attempts,last_attempt_at=excluded.last_attempt_at,"
                            "image_id=NULL,error=NULL",
                            (frame["id"], cycle, attempts + 1, now.isoformat()),
                        )
                    try:
                        self._prepare(
                            frame["id"],
                            target.isoformat(),
                            force=False,
                            offline=False,
                            purpose="scheduled",
                            cycle=cycle,
                            now=now,
                            weather_not_before=deadline,
                        )
                    except Exception as exc:
                        with self.store.connect() as db:
                            db.execute(
                                "UPDATE prepared_slots SET error=? WHERE "
                                "frame_id=? AND purpose='scheduled'",
                                (type(exc).__name__, frame["id"]),
                            )
                        log.error(
                            "Daily preparation failed frame=%s error=%s",
                            frame["id"],
                            type(exc).__name__,
                        )
                # Expired navigation buffers refresh entirely on the backend.
                navigation = self.store.active_image(self.store.frame(frame["id"]))
                if navigation is None:
                    self.request_navigation_refresh(self.store.frame(frame["id"]))
                elif not self.image_usable(navigation, self.store.frame(frame["id"]), now):
                    self.store.request_refill(frame["id"], navigation["id"])
            for site in self.settings.config.sites:
                local = now.astimezone(ZoneInfo(site.timezone))
                if local.strftime("%H:%M") >= "03:00":
                    directory = self.settings.backup_dir / local.date().isoformat()
                    if not (directory / "COMPLETE").is_file():
                        self._backup(directory)
                        self._prune_backups()
                        self._prune_history(local.date())

        self.refill_pending(now=now)

    def _prune_history(self, today):
        cutoff = (today - timedelta(days=30)).isoformat()
        with self.store.connect() as db:
            expired = db.execute(
                """SELECT * FROM images WHERE local_date<? AND id NOT IN
                   (SELECT active_image_id FROM frames WHERE active_image_id IS NOT NULL)
                   AND id NOT IN (SELECT image_id FROM prepared_slots WHERE image_id IS NOT NULL)
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
        from .backup_validation import file_digest, safe_files, verify_backup, write_manifest

        output = Path(output).absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() or output.is_symlink():
            raise ValueError("Backup destination already exists")
        # Reject source links before copying so recovery never follows external files.
        safe_files(self.settings.art_dir)
        safe_files(self.event_art.root)
        with tempfile.TemporaryDirectory(prefix=".emviary-backup-", dir=output.parent) as temporary:
            staging = Path(temporary) / "backup"
            staging.mkdir(mode=0o700)
            database = staging / "emviary.sqlite3"
            with self.store.connect() as source:
                destination = sqlite3.connect(database)
                try:
                    source.backup(destination)
                    destination.execute("PRAGMA journal_mode=DELETE")
                    if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Backup database failed integrity validation")
                finally:
                    destination.close()
            (staging / "site.json").write_text(self.settings.config.model_dump_json(indent=2))
            shutil.copytree(self.settings.art_dir, staging / "art")
            shutil.copytree(self.event_art.root, staging / "event-art")
            if not (staging / "event-art/manifest.json").exists():
                (staging / "event-art/manifest.json").write_text("[]\n")
            cache = staging / "active-cache"
            cache.mkdir()
            with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
                db.row_factory = sqlite3.Row
                images = db.execute("SELECT * FROM images WHERE hidden=0").fetchall()
                protected_ids = {
                    r[0]
                    for r in db.execute(
                        "SELECT image_id FROM prepared_slots WHERE image_id IS NOT NULL"
                    )
                }
                frames = [dict(row) for row in db.execute("SELECT * FROM frames")]
                protected = db.execute("SELECT * FROM images").fetchall()
                for frame in frames:
                    protected_ids.update(
                        frame[key]
                        for key in ("active_image_id", "max_delivered_image_id")
                        if frame.get(key) is not None
                    )
                    digest = (frame.get("last_served_etag") or "").strip('"')[:64]
                    protected_ids.update(
                        image["id"]
                        for image in protected
                        if image["frame_id"] == frame["id"] and image["body_hash"] == digest
                    )
            paths = {
                name
                for image in list(images) + [r for r in protected if r["id"] in protected_ids]
                for name in (image["path"], image["preview_path"])
            }
            for name in paths:
                source = self.cache_path(name)
                unresolved = self.settings.data_dir / name
                if any(part.is_symlink() for part in (unresolved, *unresolved.parents)):
                    raise ValueError("Backup cache contains a symbolic link")
                if not source.is_file():
                    raise ValueError("Backup is missing a retained image or preview")
                target = cache / source.relative_to(self.settings.data_dir / "cache")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            write_manifest(staging)
            verify_backup(staging, require_complete=False)
            # A complete backup becomes visible in one rename, after the final marker.
            (staging / "COMPLETE").write_text(
                stable_json(
                    {
                        "created_at": utcnow(),
                        "manifest_sha256": file_digest(staging / "integrity-manifest.json"),
                        "restore_rehearsal": "passed",
                    }
                )
                + "\n"
            )
            for entry in staging.rglob("*"):
                entry.chmod(0o700 if entry.is_dir() else 0o600)
            staging.rename(output)
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
