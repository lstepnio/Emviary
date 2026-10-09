import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def stable_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS frames (
                    id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    policy TEXT NOT NULL,
                    config_revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_contact TEXT,
                    battery INTEGER,
                    firmware TEXT,
                    last_client_etag TEXT,
                    last_served_etag TEXT,
                    active_image_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY,
                    frame_id TEXT NOT NULL REFERENCES frames(id),
                    local_date TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    profile_hash TEXT NOT NULL,
                    artwork_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    preview_path TEXT NOT NULL,
                    body_hash TEXT NOT NULL,
                    manifest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(frame_id, local_date, revision)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    frame_id TEXT NOT NULL REFERENCES frames(id),
                    local_date TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    profile_hash TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    PRIMARY KEY(frame_id, local_date, revision)
                );
                CREATE TABLE IF NOT EXISTS provider_snapshots (
                    site_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    PRIMARY KEY(site_id, provider, local_date)
                );
                CREATE TABLE IF NOT EXISTS config_overrides (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owner_sessions (
                    token_hash TEXT PRIMARY KEY,
                    csrf TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS image_refills (
                    frame_id TEXT PRIMARY KEY REFERENCES frames(id),
                    consumed_image_id INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    attempt_date TEXT,
                    last_attempt_at TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS excluded_artworks (id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS bird_render_counts (
                    scientific_name TEXT PRIMARY KEY, common_name TEXT NOT NULL,
                    renders INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS battery_samples (
                    id INTEGER PRIMARY KEY,
                    frame_id TEXT NOT NULL REFERENCES frames(id),
                    recorded_at TEXT NOT NULL,
                    bucket INTEGER NOT NULL,
                    percent INTEGER NOT NULL CHECK(percent BETWEEN 0 AND 100),
                    voltage REAL,
                    charging INTEGER,
                    usb_connected INTEGER,
                    UNIQUE(frame_id, bucket)
                );
                CREATE INDEX IF NOT EXISTS battery_samples_frame_time
                    ON battery_samples(frame_id, recorded_at);
                PRAGMA user_version=3;
            """)

        with self.connect() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(images)")}
            if "hidden" not in columns:
                db.execute("ALTER TABLE images ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
                for row in db.execute("SELECT manifest FROM images").fetchall():
                    self.count_render(db, json.loads(row["manifest"]))

    @staticmethod
    def count_render(db, plan):
        species = {
            a["scientific_name"]: a["common_name"]
            for a in plan.get("artworks", [plan["artwork"]])
            if a.get("scientific_name") and not a.get("event_only")
        }
        for scientific, common in species.items():
            db.execute(
                """INSERT INTO bird_render_counts VALUES(?,?,1)
                   ON CONFLICT(scientific_name) DO UPDATE SET renders=renders+1""",
                (scientific, common),
            )

    def bird_counts(self):
        with self.connect() as db:
            return {
                r["scientific_name"]: r["renders"]
                for r in db.execute("SELECT * FROM bird_render_counts")
            }

    def excluded_artworks(self):
        with self.connect() as db:
            return {r[0] for r in db.execute("SELECT id FROM excluded_artworks")}

    def navigation_image(self, frame, direction, client_tag):
        digest = client_tag.removeprefix("W/").strip('"').split("-c")[0]
        with self.connect() as db:
            cursor = db.execute(
                "SELECT * FROM images WHERE frame_id=? AND body_hash=? ORDER BY id DESC LIMIT 1",
                (frame["id"], digest),
            ).fetchone()
            if cursor is None:
                return self.active_image(frame)
            active = db.execute(
                "SELECT * FROM images WHERE id=? AND frame_id=? AND hidden=0",
                (frame["active_image_id"], frame["id"]),
            ).fetchone()
            if (
                direction == "next"
                and active
                and active["id"] > cursor["id"]
                and json.loads(active["manifest"]).get("special_day_test")
            ):
                return dict(active)
            comparison, order = ("<", "DESC") if direction == "previous" else (">", "ASC")
            row = db.execute(
                f"SELECT * FROM images WHERE frame_id=? AND hidden=0 AND id{comparison}? "
                f"ORDER BY id {order} LIMIT 1",
                (frame["id"], cursor["id"]),
            ).fetchone()
            return dict(row or cursor)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def frame(self, frame_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM frames WHERE id=?", (frame_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown frame: {frame_id}")
        return dict(row)

    def frames(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM frames ORDER BY id")]

    def add_frame(self, frame_id, policy):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute(
                "INSERT INTO frames(id,site_id,token_hash,policy,created_at) VALUES(?,?,?,?,?)",
                (
                    frame_id,
                    policy.site_id,
                    token_hash(token),
                    stable_json(policy.model_dump()),
                    utcnow(),
                ),
            )
        return token

    def authenticate(self, token):
        if not token or len(token) > 128:
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM frames WHERE token_hash=?", (token_hash(token),)
            ).fetchone()
        return dict(row) if row else None

    def rotate_token(self, frame_id):
        self.frame(frame_id)
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("UPDATE frames SET token_hash=? WHERE id=?", (token_hash(token), frame_id))
        return token

    def set_policy(self, frame_id, policy):
        self.frame(frame_id)
        with self.connect() as db:
            db.execute(
                "UPDATE frames SET policy=?,site_id=?,config_revision=config_revision+1 WHERE id=?",
                (stable_json(policy.model_dump()), policy.site_id, frame_id),
            )

    def active_image(self, frame):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM images WHERE id=? AND frame_id=?",
                (frame["active_image_id"], frame["id"]),
            ).fetchone()
        if row and row["hidden"]:
            with self.connect() as db:
                row = db.execute(
                    "SELECT * FROM images WHERE frame_id=? AND hidden=0 ORDER BY id DESC LIMIT 1",
                    (frame["id"],),
                ).fetchone()
        return dict(row) if row else None

    def telemetry(
        self,
        frame_id,
        battery,
        firmware,
        client_etag,
        served_etag,
        battery_voltage=None,
        battery_charging=None,
        usb_connected=None,
    ):
        now = datetime.now(UTC)
        battery = battery if type(battery) is int and 0 <= battery <= 100 else None
        with self.connect() as db:
            updated = db.execute(
                """UPDATE frames SET last_contact=?,battery=COALESCE(?,battery),
                   firmware=COALESCE(?,firmware),last_client_etag=?,last_served_etag=?
                   WHERE id=?""",
                (now.isoformat(), battery, firmware, client_etag, served_etag, frame_id),
            )
            if updated.rowcount == 0:
                return  # A frame can be removed after an in-flight download was authenticated.
            if battery is not None:
                # One sample per quarter hour prevents button navigation from weighting trends.
                db.execute(
                    """INSERT INTO battery_samples
                       (frame_id,recorded_at,bucket,percent,voltage,charging,usb_connected)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(frame_id,bucket) DO UPDATE SET
                       recorded_at=excluded.recorded_at,percent=excluded.percent,
                       voltage=excluded.voltage,charging=excluded.charging,
                       usb_connected=excluded.usb_connected""",
                    (
                        frame_id,
                        now.isoformat(),
                        int(now.timestamp()) // 900,
                        battery,
                        battery_voltage,
                        battery_charging,
                        usb_connected,
                    ),
                )
                db.execute(
                    "DELETE FROM battery_samples WHERE recorded_at<?",
                    ((now - timedelta(days=365)).isoformat(),),
                )

    def battery_samples(self, frame_id):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM battery_samples WHERE frame_id=? ORDER BY recorded_at,id",
                    (frame_id,),
                )
            ]

    def request_refill(self, frame_id, image_id):
        with self.connect() as db:
            db.execute(
                """INSERT INTO image_refills(frame_id,consumed_image_id)
                   SELECT ?,? WHERE EXISTS(SELECT 1 FROM frames WHERE id=?)
                   ON CONFLICT(frame_id) DO UPDATE SET
                   consumed_image_id=excluded.consumed_image_id,attempts=0,
                   attempt_date=NULL,last_attempt_at=NULL,error=NULL
                   WHERE excluded.consumed_image_id > image_refills.consumed_image_id""",
                (frame_id, image_id, frame_id),
            )

    def pending_refills(self, frame_id=None):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM image_refills" + (" WHERE frame_id=?" if frame_id else ""),
                (frame_id,) if frame_id else (),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_refill(self, frame_id, consumed_image_id):
        with self.connect() as db:
            db.execute(
                "DELETE FROM image_refills WHERE frame_id=? AND consumed_image_id=?",
                (frame_id, consumed_image_id),
            )

    def snapshot(self, site_id, provider, local_date=None):
        with self.connect() as db:
            if local_date:
                row = db.execute(
                    """SELECT * FROM provider_snapshots
                       WHERE site_id=? AND provider=? AND local_date=?""",
                    (site_id, provider, local_date),
                ).fetchone()
            else:
                row = db.execute(
                    """SELECT * FROM provider_snapshots WHERE site_id=? AND provider=?
                       ORDER BY received_at DESC LIMIT 1""",
                    (site_id, provider),
                ).fetchone()
        return dict(row) if row else None

    def save_snapshot(self, site_id, provider, local_date, payload):
        with self.connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO provider_snapshots
                   VALUES(?,?,?,?,?)""",
                (site_id, provider, local_date, stable_json(payload), utcnow()),
            )
