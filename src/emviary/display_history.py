"""Authenticated device display evidence, separate from server image preparation.

Emviary 0.8.10 persists its ETag and admits the offline-cache cursor only after
panel refresh succeeds. Reports describe a previous operation, not this response.
A transfer completing on the server never supplies display confirmation.
"""

import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .status_data import timestamp

TAG = re.compile(r'^(?:W/)?"?([a-f0-9]{64})(?:-c[0-9]{1,20})?"?$')


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS image_transfers (
            id INTEGER PRIMARY KEY,
            frame_id TEXT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
            image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
            body_hash TEXT NOT NULL,
            response_status INTEGER NOT NULL CHECK(response_status IN (200,304)),
            sent_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS image_transfers_frame_hash
            ON image_transfers(frame_id,body_hash,id DESC);
        CREATE TABLE IF NOT EXISTS image_display_reports (
            id INTEGER PRIMARY KEY,
            frame_id TEXT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
            image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
            body_hash TEXT NOT NULL,
            reported_at TEXT NOT NULL,
            source TEXT NOT NULL,
            firmware TEXT,
            evidence_key TEXT NOT NULL,
            recovered INTEGER NOT NULL DEFAULT 0,
            UNIQUE(frame_id,evidence_key)
        );
        CREATE INDEX IF NOT EXISTS image_display_reports_frame_time
            ON image_display_reports(frame_id,reported_at DESC,id DESC);
        CREATE TABLE IF NOT EXISTS display_history_state (
            id INTEGER PRIMARY KEY CHECK(id=1),
            started_at TEXT NOT NULL,
            legacy_import_complete INTEGER NOT NULL DEFAULT 0
        );
    """)


def supported(firmware):
    # Only the audited firmware contract qualifies historical cursor evidence.
    return firmware in {"v0.8.10", "0.8.10"}


def reported_label(image, timezone):
    stamp = timestamp(image.get("reported_at"))
    if stamp is None:
        return "Display time unavailable"
    when = stamp.astimezone(ZoneInfo(timezone)).strftime("%b %-d, %-I:%M %p %Z")
    return "Frame reported " + when


HISTORY_NOTE = (
    "Only pictures the frame reported as displayed appear here. "
    "Reports can arrive on a later wake. Older history and offline rotations may have gaps."
)


class DisplayHistory:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _image(db, frame_id, image_id, observed):
        row = db.execute(
            "SELECT * FROM images WHERE id=? AND frame_id=?", (image_id, frame_id)
        ).fetchone()
        if row and (created := timestamp(row["created_at"])) is not None and created <= observed:
            return dict(row)
        return None

    def _cursor(self, db, frame_id, metrics, observed):
        image_id = metrics.get("offline_image_id")
        if type(image_id) is not int or image_id <= 0:
            return None
        image = self._image(db, frame_id, image_id, observed)
        if not image:
            return None
        if (
            metrics.get("offline_mode") is False
            and metrics.get("previous_result") in {"success", "unchanged"}
            and metrics.get("previous_http_status") in {200, 304}
        ):
            return image, "cloud_cache_report"
        # Offline rotation can succeed even though the cloud fetch failed. The
        # firmware advances this cursor/rotation count only after panel success.
        if (
            metrics.get("offline_mode") is True
            and metrics.get("offline_rotations", 0) > 0
            and metrics.get("previous_result") in {"success", "unchanged", "failed"}
        ):
            return image, "offline_cache_report"
        return None

    @staticmethod
    def _insert(db, frame_id, image, stamp, source, firmware, key, recovered=False):
        db.execute(
            "INSERT OR IGNORE INTO image_display_reports"
            "(frame_id,image_id,body_hash,reported_at,source,firmware,evidence_key,recovered) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                frame_id,
                image["id"],
                image["body_hash"],
                stamp.isoformat(),
                source,
                firmware,
                key,
                int(recovered),
            ),
        )

    def import_legacy(self):
        from .diagnostics import parse_metrics

        now = self.clock()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO display_history_state(id,started_at) VALUES(1,?)",
                (now.isoformat(),),
            )
            if db.execute("SELECT legacy_import_complete FROM display_history_state").fetchone()[0]:
                return
            for row in db.execute("SELECT * FROM device_samples ORDER BY id").fetchall():
                if not supported(row["firmware"]):
                    continue
                observed = timestamp(row["recorded_at"])
                if observed is None or observed > now + timedelta(minutes=5):
                    continue
                metrics = parse_metrics(row["metrics"])
                if not metrics:
                    continue
                evidence = self._cursor(db, row["frame_id"], metrics, observed)
                if evidence:
                    image, source = evidence
                    self._insert(
                        db,
                        row["frame_id"],
                        image,
                        observed,
                        source,
                        row["firmware"],
                        "legacy-sample:" + str(row["id"]),
                        recovered=True,
                    )
            db.execute("UPDATE display_history_state SET legacy_import_complete=1")

    def observe(self, frame_id, client_tag, metrics, firmware, key=None):
        from .diagnostics import parse_metrics

        if not supported(firmware) or not isinstance(metrics, dict):
            return
        metrics = parse_metrics(json.dumps(metrics))
        if not metrics:
            return
        now = self.clock()
        with self.store.connect() as db:
            evidence = self._cursor(db, frame_id, metrics, now)
            match = TAG.fullmatch(client_tag) if isinstance(client_tag, str) else None
            cloud_success = (
                metrics.get("offline_mode") is False
                and metrics.get("previous_result") in {"success", "unchanged"}
                and metrics.get("previous_http_status") in {200, 304}
            )
            if match and cloud_success:
                digest = match[1]
                if evidence and evidence[0]["body_hash"] != digest:
                    return  # Conflicting evidence never confirms either candidate.
                if not evidence:
                    rows = db.execute(
                        "SELECT i.* FROM image_transfers t JOIN images i ON i.id=t.image_id "
                        "WHERE t.frame_id=? AND t.body_hash=? AND t.response_status=200 "
                        "ORDER BY t.id DESC LIMIT 1",
                        (frame_id, digest),
                    ).fetchall()
                    if not rows:
                        rows = db.execute(
                            "SELECT * FROM images WHERE frame_id=? AND body_hash=? LIMIT 2",
                            (frame_id, digest),
                        ).fetchall()
                    if len(rows) == 1:
                        image = self._image(db, frame_id, rows[0]["id"], now)
                        if image:
                            evidence = image, "persisted_etag"
                if evidence:
                    evidence = evidence[0], "persisted_etag"
            if evidence:
                image, source = evidence
                self._insert(
                    db,
                    frame_id,
                    image,
                    now,
                    source,
                    firmware,
                    key or "request:" + secrets.token_hex(16),
                )

    def sent(self, frame_id, image_id, status):
        if status not in (200, 304):
            raise ValueError("Only completed image responses are transfers")
        with self.store.connect() as db:
            image = db.execute(
                "SELECT * FROM images WHERE frame_id=? AND id=?", (frame_id, image_id)
            ).fetchone()
            if image:
                db.execute(
                    "INSERT INTO image_transfers"
                    "(frame_id,image_id,body_hash,response_status,sent_at) VALUES(?,?,?,?,?)",
                    (frame_id, image_id, image["body_hash"], status, self.clock().isoformat()),
                )

    def past(self, frame_id, current_id=None, limit=10):
        from .compositions import composition_key, distinct_compositions

        with self.store.connect() as db:
            current = db.execute(
                "SELECT * FROM images WHERE frame_id=? AND id=?", (frame_id, current_id)
            ).fetchone()
            # Drive from the narrow report index, not an ID-range of all renders.
            rows = db.execute(
                "SELECT i.*,r.reported_at,r.source,r.recovered FROM image_display_reports r "
                "INDEXED BY image_display_reports_frame_time JOIN images i ON i.id=r.image_id "
                "WHERE r.frame_id=? AND i.frame_id=? AND i.hidden=0 "
                "ORDER BY r.reported_at DESC,r.id DESC",
                (frame_id, frame_id),
            )
            return distinct_compositions(
                (dict(row) for row in rows),
                exclude=[composition_key(dict(current))] if current else [],
                limit=min(10, max(1, limit)),
            )

    def latest(self, frame_id, body_hash=None):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT i.*,r.reported_at,r.source,r.recovered FROM image_display_reports r "
                "JOIN images i ON i.id=r.image_id WHERE r.frame_id=? AND i.frame_id=? "
                "AND i.hidden=0"
                + (" AND r.body_hash=?" if body_hash else "")
                + " ORDER BY r.reported_at DESC,r.id DESC LIMIT 1",
                (frame_id, frame_id, body_hash) if body_hash else (frame_id, frame_id),
            ).fetchone()
            return dict(row) if row else None
