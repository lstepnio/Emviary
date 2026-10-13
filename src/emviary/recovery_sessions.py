"""Owner scoped recovery leases and positive device evidence, never serial logs."""

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .store import RevisionConflict, stable_json, token_hash

LEASE_SECONDS = 90
RETENTION_DAYS = 7
MAX_EVENTS = 128
MAX_SESSIONS_PER_FRAME = 32
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
DEVICE_ID = re.compile(r"^[0-9a-f]{12}$")
BOOT_ID = re.compile(r"^[0-9a-f]{16}$")
PHASES = {"booted", "configured", "network_ready", "image_verified", "panel_refreshed", "failed"}


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS recovery_sessions (
            id TEXT PRIMARY KEY, frame_id TEXT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
            nonce TEXT NOT NULL, firmware TEXT NOT NULL, bundle_sha256 TEXT NOT NULL,
            config_revision INTEGER NOT NULL, device_id TEXT, boot_id TEXT,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, lease_expires_at TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active', evidence TEXT NOT NULL DEFAULT '{}',
            image_id INTEGER, image_sha256 TEXT, event_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS recovery_sessions_frame ON recovery_sessions(frame_id);
        CREATE TABLE IF NOT EXISTS recovery_events (
            session_id TEXT NOT NULL REFERENCES recovery_sessions(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL, recorded_at TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(session_id,sequence)
        );
        CREATE TABLE IF NOT EXISTS recovery_pending_bindings (
            session_id TEXT PRIMARY KEY REFERENCES recovery_sessions(id) ON DELETE CASCADE,
            frame_id TEXT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE, previous_token_hash TEXT NOT NULL,
            expected_revision INTEGER NOT NULL, policy TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recovery_device_identity (
            frame_id TEXT PRIMARY KEY REFERENCES frames(id) ON DELETE CASCADE,
            device_id TEXT NOT NULL
        );
    """)


def lease_guard(db, frame_id, recovery_session_id=None):
    row = db.execute(
        "SELECT id FROM recovery_sessions WHERE frame_id=? AND state='active' "
        "AND lease_expires_at>? AND expires_at>? LIMIT 1",
        (frame_id, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    ).fetchone()
    if row and row["id"] != recovery_session_id:
        raise RevisionConflict("USB recovery is using this frame. Finish or cancel it first.")


class RecoverySessions:
    def __init__(self, store, now=None):
        self.store = store
        self.clock = now or (lambda: datetime.now(UTC))

    @staticmethod
    def picture_verified(session, evidence):
        return (
            all(
                evidence.get(phase)
                for phase in ("booted", "cloud_requested", "image_verified", "panel_refreshed")
            )
            and not evidence.get("error")
            and bool(BOOT_ID.fullmatch(session.get("boot_id") or ""))
            and bool(DEVICE_ID.fullmatch(session.get("device_id") or ""))
            and session.get("image_id") is not None
            and bool(re.fullmatch(r"[a-f0-9]{64}", session.get("image_sha256") or ""))
        )

    def _session(self, db, session_id, frame_id=None, active=True):
        row = db.execute("SELECT * FROM recovery_sessions WHERE id=?", (session_id,)).fetchone()
        if not row or frame_id is not None and row["frame_id"] != frame_id:
            raise HTTPException(404, "Unknown recovery session")
        row = dict(row)
        if active and (row["state"] != "active" or row["expires_at"] <= self.clock().isoformat()):
            raise HTTPException(409, "Recovery session expired or finished")
        return row

    def create(self, frame_id, manifest, device_id=None):
        if device_id and not DEVICE_ID.fullmatch(device_id):
            raise HTTPException(400, "Invalid device identity")
        now = self.clock()
        digest = hashlib.sha256(stable_json(manifest).encode()).hexdigest()
        session_id, nonce = secrets.token_hex(16), secrets.token_hex(24)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            frame = db.execute("SELECT * FROM frames WHERE id=?", (frame_id,)).fetchone()
            if not frame:
                raise HTTPException(404, "Unknown frame")
            db.execute(
                "DELETE FROM recovery_sessions WHERE created_at<?",
                ((now - timedelta(days=RETENTION_DAYS)).isoformat(),),
            )
            db.execute(
                "DELETE FROM recovery_sessions WHERE frame_id=? AND id NOT IN "
                "(SELECT id FROM recovery_sessions WHERE frame_id=? "
                "ORDER BY created_at DESC LIMIT ?) AND id NOT IN "
                "(SELECT session_id FROM recovery_pending_bindings WHERE expires_at>?)",
                (frame_id, frame_id, MAX_SESSIONS_PER_FRAME - 1, now.isoformat()),
            )
            busy = db.execute(
                "SELECT id FROM recovery_sessions WHERE frame_id=? AND state='active' "
                "AND lease_expires_at>? AND expires_at>?",
                (frame_id, now.isoformat(), now.isoformat()),
            ).fetchone()
            if busy:
                raise HTTPException(409, "Another recovery session is using this frame")
            pinned = db.execute(
                "SELECT device_id FROM recovery_device_identity WHERE frame_id=?", (frame_id,)
            ).fetchone()
            if pinned and device_id and pinned[0] != device_id:
                raise HTTPException(409, "USB device does not match this frame")
            pending = db.execute(
                "SELECT s.*,p.previous_token_hash,p.expected_revision FROM recovery_sessions s "
                "JOIN recovery_pending_bindings p ON p.session_id=s.id "
                "WHERE p.frame_id=? AND p.expires_at>? ORDER BY s.created_at LIMIT 1",
                (frame_id, now.isoformat()),
            ).fetchone()
            if pending:
                detail = {
                    "code": "pending_binding_bundle_mismatch",
                    "message": "Finish the previous settings transfer with its recovery files.",
                    "session_id": pending["id"],
                    "expected_firmware": pending["firmware"],
                }
                if pending["firmware"] != manifest["version"] or pending["bundle_sha256"] != digest:
                    raise HTTPException(409, detail)
                if pending["device_id"] and device_id and pending["device_id"] != device_id:
                    raise HTTPException(
                        409,
                        dict(
                            detail,
                            code="pending_binding_device_mismatch",
                            message="USB device does not match this frame.",
                        ),
                    )
                if (
                    frame["token_hash"] != pending["previous_token_hash"]
                    or frame["config_revision"] != pending["expected_revision"]
                ):
                    raise HTTPException(
                        409,
                        dict(
                            detail,
                            code="pending_binding_settings_changed",
                            message="Saved settings changed during transfer.",
                        ),
                    )
                session_id = pending["id"]
                db.execute(
                    "UPDATE recovery_sessions SET state='active',lease_expires_at=? WHERE id=?",
                    ((now + timedelta(seconds=LEASE_SECONDS)).isoformat(), session_id),
                )
            else:
                db.execute(
                    "UPDATE recovery_sessions SET state='superseded' WHERE frame_id=? "
                    "AND state='active'",
                    (frame_id,),
                )
                db.execute(
                    "INSERT INTO recovery_sessions(id,frame_id,nonce,firmware,bundle_sha256,"
                    "config_revision,device_id,created_at,expires_at,lease_expires_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        session_id,
                        frame_id,
                        nonce,
                        manifest["version"],
                        digest,
                        frame["config_revision"],
                        pinned[0] if pinned else device_id,
                        now.isoformat(),
                        (now + timedelta(hours=24)).isoformat(),
                        (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                    ),
                )
        return self.get(frame_id, session_id)

    def get(self, frame_id, session_id):
        with self.store.connect() as db:
            row = self._session(db, session_id, frame_id, active=False)
            pending = db.execute(
                "SELECT session_id,expires_at FROM recovery_pending_bindings WHERE frame_id=?",
                (frame_id,),
            ).fetchone()
            events = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM recovery_events WHERE session_id=? ORDER BY sequence",
                    (session_id,),
                )
            ]
        evidence = json.loads(row["evidence"])
        return {
            "session_id": row["id"],
            "nonce": row["nonce"],
            "frame_id": row["frame_id"],
            "expected_firmware": row["firmware"],
            "bundle_sha256": row["bundle_sha256"],
            "config_revision": row["config_revision"],
            "device_id": row["device_id"],
            "boot_id": row["boot_id"],
            "lease_expires_at": row["lease_expires_at"],
            "expires_at": row["expires_at"],
            "state": row["state"],
            "evidence": evidence,
            "verification": "verified"
            if self.picture_verified(row, evidence)
            else "failed"
            if evidence.get("error")
            else "pending",
            "image_id": row["image_id"],
            "image_sha256": row["image_sha256"],
            "events": events,
            "pending_binding": {
                "session_id": pending["session_id"],
                "expires_at": pending["expires_at"],
                "expired": pending["expires_at"] <= self.clock().isoformat(),
            }
            if pending
            else None,
        }

    def renew(self, frame_id, session_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._session(db, session_id, frame_id)
            lease_guard(db, frame_id, session_id)
            db.execute(
                "UPDATE recovery_sessions SET lease_expires_at=? WHERE id=?",
                ((self.clock() + timedelta(seconds=LEASE_SECONDS)).isoformat(), session_id),
            )
        return self.get(frame_id, session_id)

    def transition_boot(self, frame_id, session_id, data):
        """An owner-validated USB HELLO starts fresh evidence for this exact device boot."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id, frame_id)
            lease_guard(db, frame_id, session_id)
            if session["lease_expires_at"] <= self.clock().isoformat():
                raise HTTPException(409, "Resume recovery before verifying the frame boot")
            for key, pattern in (("device_id", DEVICE_ID), ("boot_id", BOOT_ID)):
                if not isinstance(data.get(key), str) or not pattern.fullmatch(data[key]):
                    raise HTTPException(400, "Invalid recovery device identity")
            for key, expected in (
                ("firmware", session["firmware"]),
                ("bundle_sha256", session["bundle_sha256"]),
            ):
                if not isinstance(data.get(key), str) or not secrets.compare_digest(
                    data[key].encode(), expected.encode()
                ):
                    raise HTTPException(409, "Recovery firmware or bundle does not match")
            pinned = db.execute(
                "SELECT device_id FROM recovery_device_identity WHERE frame_id=?", (frame_id,)
            ).fetchone()
            expected_device = session["device_id"] or (pinned[0] if pinned else None)
            first_identification = not expected_device and not session["boot_id"]
            if (
                not first_identification
                and data["device_id"] != expected_device
                or (pinned and pinned[0] != data["device_id"])
            ):
                raise HTTPException(409, "USB device does not match the selected frame")
            if session["boot_id"] != data["boot_id"]:
                previous = json.loads(session["evidence"])
                evidence = {"booted": self.clock().isoformat()}
                if previous.get("binding_activated"):
                    evidence["binding_activated"] = previous["binding_activated"]
                db.execute(
                    "UPDATE recovery_sessions SET device_id=?,boot_id=?,evidence=?,"
                    "image_id=NULL,image_sha256=NULL WHERE id=?",
                    (data["device_id"], data["boot_id"], stable_json(evidence), session_id),
                )
        return self.get(frame_id, session_id)

    def event(self, frame_id, session_id, data):
        # Strict structured vocabulary: no free form trace, nested evidence, credentials or logs.
        allowed = {"attempt_id", "state", "operation", "error", "elapsed_ms"}
        if not isinstance(data, dict) or set(data) - allowed:
            raise HTTPException(400, "Only structured recovery checkpoints are accepted")
        for key, value in data.items():
            if key == "elapsed_ms":
                if type(value) is not int or not 0 <= value <= 86400000:
                    raise HTTPException(400, "Invalid checkpoint timing")
            elif not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise HTTPException(400, "Invalid checkpoint code")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id, frame_id)
            if session["event_count"] >= MAX_EVENTS:
                raise HTTPException(429, "Recovery checkpoint limit reached")
            sequence = session["event_count"] + 1
            db.execute(
                "INSERT INTO recovery_events VALUES(?,?,?,?)",
                (session_id, sequence, self.clock().isoformat(), stable_json(data)),
            )
            db.execute(
                "UPDATE recovery_sessions SET event_count=? WHERE id=?", (sequence, session_id)
            )
        return {"sequence": sequence}

    def stage_binding(self, frame, policy, token, session_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id, frame["id"])
            lease_guard(db, frame["id"], session_id)
            existing = db.execute(
                "SELECT * FROM recovery_pending_bindings WHERE frame_id=? AND expires_at>?",
                (frame["id"], self.clock().isoformat()),
            ).fetchone()
            if existing and (
                existing["session_id"] != session_id or existing["token_hash"] != token_hash(token)
            ):
                raise HTTPException(
                    409,
                    {
                        "message": "A settings transfer is unfinished. Resume that session.",
                        "session_id": existing["session_id"],
                    },
                )
            db.execute(
                "DELETE FROM recovery_pending_bindings WHERE frame_id=? AND expires_at<=?",
                (frame["id"], self.clock().isoformat()),
            )
            current = db.execute("SELECT * FROM frames WHERE id=?", (frame["id"],)).fetchone()
            if (
                current["config_revision"] != frame["config_revision"]
                or current["token_hash"] != frame["token_hash"]
            ):
                raise RevisionConflict(
                    "Frame settings changed. Resume recovery with saved settings."
                )
            db.execute(
                "INSERT INTO recovery_pending_bindings VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET token_hash=excluded.token_hash,"
                "policy=excluded.policy,expires_at=excluded.expires_at",
                (
                    session_id,
                    frame["id"],
                    token_hash(token),
                    frame["token_hash"],
                    frame["config_revision"],
                    stable_json(policy.model_dump()),
                    session["expires_at"],
                ),
            )
            # The response configuration is the pending generation until successful activation.
            db.execute(
                "UPDATE recovery_sessions SET config_revision=? WHERE id=?",
                (frame["config_revision"] + 1, session_id),
            )

    def authenticate(self, token, session_id, nonce):
        if not token or len(token) > 128:
            return None
        with self.store.connect() as db:
            pending = db.execute(
                "SELECT p.*,s.nonce,s.state FROM recovery_pending_bindings p "
                "JOIN recovery_sessions s ON s.id=p.session_id WHERE p.token_hash=? "
                "AND p.session_id=? AND p.expires_at>?",
                (token_hash(token), session_id, self.clock().isoformat()),
            ).fetchone()
            if (
                not pending
                or pending["state"] not in {"active", "cancelled", "superseded"}
                or not secrets.compare_digest(pending["nonce"].encode(), nonce.encode())
            ):
                return None
            row = db.execute("SELECT * FROM frames WHERE id=?", (pending["frame_id"],)).fetchone()
            if not row:
                return None
            frame = dict(row)
            frame["policy"] = pending["policy"]
            frame["config_revision"] = pending["expected_revision"] + 1
            frame["_recovery_pending_session_id"] = session_id
            frame["_recovery_pending_token_hash"] = token_hash(token)
            return frame

    def _correlate(self, db, frame, data):
        session = self._session(db, data.get("session_id"), frame["id"], active=False)
        pending_handoff = None
        if frame.get("_recovery_pending_session_id") == session["id"]:
            pending_handoff = db.execute(
                "SELECT * FROM recovery_pending_bindings WHERE session_id=? AND token_hash=? "
                "AND expires_at>?",
                (
                    session["id"],
                    frame.get("_recovery_pending_token_hash"),
                    self.clock().isoformat(),
                ),
            ).fetchone()
        activated_handoff = json.loads(session["evidence"]).get("binding_activated")
        if session["expires_at"] <= self.clock().isoformat() or session["state"] not in {
            "active",
            "cancelled",
            "superseded",
        }:
            raise HTTPException(409, "Recovery session expired or finished")
        if (
            not pending_handoff
            and not activated_handoff
            and (
                session["state"] != "active"
                or session["lease_expires_at"] <= self.clock().isoformat()
            )
        ):
            raise HTTPException(409, "Renew recovery before checking the frame")
        for key, expected in (
            ("nonce", session["nonce"]),
            ("firmware", session["firmware"]),
            ("bundle_sha256", session["bundle_sha256"]),
        ):
            if not isinstance(data.get(key), str) or not secrets.compare_digest(
                data[key].encode(), expected.encode()
            ):
                raise HTTPException(409, "Recovery challenge or firmware does not match")
        for key, pattern in (("device_id", DEVICE_ID), ("boot_id", BOOT_ID)):
            if not isinstance(data.get(key), str) or not pattern.fullmatch(data[key]):
                raise HTTPException(400, "Invalid recovery device identity")
        if session["device_id"] and session["device_id"] != data["device_id"]:
            raise HTTPException(409, "USB device does not match this frame")
        if session["boot_id"] and session["boot_id"] != data["boot_id"]:
            raise HTTPException(409, "Verify the current frame boot through USB before continuing")
        pinned = db.execute(
            "SELECT device_id FROM recovery_device_identity WHERE frame_id=?", (frame["id"],)
        ).fetchone()
        if pinned and pinned[0] != data["device_id"]:
            raise HTTPException(409, "Device does not match the registered frame")
        current = db.execute(
            "SELECT config_revision FROM frames WHERE id=?", (frame["id"],)
        ).fetchone()
        if frame["config_revision"] != session["config_revision"] or current[0] not in {
            session["config_revision"],
            session["config_revision"] - 1,
        }:
            raise HTTPException(409, "Saved settings changed during recovery")
        return session

    def image_requested(self, frame, data, record, token):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._correlate(db, frame, data)
            pending = db.execute(
                "SELECT * FROM recovery_pending_bindings WHERE session_id=?", (session["id"],)
            ).fetchone()
            if pending and secrets.compare_digest(pending["token_hash"], token_hash(token)):
                changed = db.execute(
                    "UPDATE frames SET token_hash=?,policy=?,site_id=?,"
                    "config_revision=config_revision+1 "
                    "WHERE id=? AND token_hash=? AND config_revision=?",
                    (
                        pending["token_hash"],
                        pending["policy"],
                        json.loads(pending["policy"])["site_id"],
                        frame["id"],
                        pending["previous_token_hash"],
                        pending["expected_revision"],
                    ),
                )
                if not changed.rowcount:
                    raise HTTPException(409, "Binding changed during recovery")
                db.execute(
                    "DELETE FROM recovery_pending_bindings WHERE session_id=?", (session["id"],)
                )
                db.execute("DELETE FROM frame_network_contacts WHERE frame_id=?", (frame["id"],))
            evidence = json.loads(session["evidence"])
            if (
                session["boot_id"] != data["boot_id"]
                or session["image_sha256"] != record["body_hash"]
            ):
                evidence = {}
            if pending:
                evidence["binding_activated"] = self.clock().isoformat()
            elif json.loads(session["evidence"]).get("binding_activated"):
                evidence["binding_activated"] = json.loads(session["evidence"])["binding_activated"]
            evidence["cloud_requested"] = self.clock().isoformat()
            evidence["booted"] = evidence.get("booted", self.clock().isoformat())
            db.execute(
                "INSERT OR IGNORE INTO recovery_device_identity VALUES(?,?)",
                (frame["id"], data["device_id"]),
            )
            db.execute(
                "UPDATE recovery_sessions SET device_id=?,boot_id=?,evidence=?,"
                "image_id=?,image_sha256=? WHERE id=?",
                (
                    data["device_id"],
                    data["boot_id"],
                    stable_json(evidence),
                    record["id"],
                    record["body_hash"],
                    session["id"],
                ),
            )

    def acknowledge(self, frame, data):
        phase = data.get("phase")
        if phase not in PHASES:
            raise HTTPException(400, "Unknown recovery evidence phase")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._correlate(db, frame, data)
            if session["boot_id"] and session["boot_id"] != data["boot_id"]:
                raise HTTPException(409, "Recovery acknowledgment is from an earlier boot")
            evidence = json.loads(session["evidence"])
            if phase in {"image_verified", "panel_refreshed"}:
                if (
                    not session["image_sha256"]
                    or data.get("image_sha256") != session["image_sha256"]
                ):
                    raise HTTPException(
                        409, "Picture acknowledgment does not match the served image"
                    )
                if phase == "panel_refreshed" and "image_verified" not in evidence:
                    raise HTTPException(
                        409, "Verify the complete picture before confirming display"
                    )
                if phase == "panel_refreshed" and data.get("error"):
                    raise HTTPException(400, "Failed display cannot acknowledge successful refresh")
            if phase == "failed":
                error = data.get("error", "unknown")
                if not isinstance(error, str) or not IDENTIFIER.fullmatch(error):
                    raise HTTPException(400, "Invalid recovery error code")
                evidence.pop("panel_refreshed", None)
                evidence["error"] = error
            elif phase == "panel_refreshed":
                evidence.pop("failed", None)
                evidence.pop("error", None)
            evidence[phase] = self.clock().isoformat()
            db.execute(
                "UPDATE recovery_sessions SET device_id=?,boot_id=?,evidence=? WHERE id=?",
                (data["device_id"], data["boot_id"], stable_json(evidence), session["id"]),
            )
        return {"accepted": True, "phase": phase}

    def finish(self, frame_id, session_id, physical_confirmed=False, cancel=False, expected=None):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id, frame_id, active=False)
            if (
                not cancel
                and expected is not None
                and any(
                    not expected.get(key) or str(expected[key]) != str(session[key])
                    for key in ("boot_id", "image_id", "image_sha256")
                )
            ):
                raise HTTPException(
                    409,
                    {
                        "code": "picture_changed",
                        "message": (
                            "The verified boot or picture changed. "
                            "Verify its current picture before finishing."
                        ),
                    },
                )
            if session["state"] == ("cancelled" if cancel else "completed"):
                return self.get(frame_id, session_id)
            if session["state"] != "active" or session["expires_at"] <= self.clock().isoformat():
                raise HTTPException(409, "Recovery session already ended")
            evidence = json.loads(session["evidence"])
            if not cancel and (
                not physical_confirmed or not self.picture_verified(session, evidence)
            ):
                raise HTTPException(
                    409, "Verify the picture and confirm its physical appearance first"
                )
            if not cancel:
                evidence["physical_confirmed"] = self.clock().isoformat()
            db.execute(
                "UPDATE recovery_sessions SET state=?,lease_expires_at=?,evidence=? WHERE id=?",
                (
                    "cancelled" if cancel else "completed",
                    self.clock().isoformat(),
                    stable_json(evidence),
                    session_id,
                ),
            )
            if not cancel:
                db.execute(
                    "DELETE FROM recovery_pending_bindings WHERE session_id=?", (session_id,)
                )
        return self.get(frame_id, session_id)


def promote_pending_token(service, frame_id, session_id):
    """Promote a private restore token only while its activated DB generation is current.

    Failure leaves the pending file intact for a later retry. Disk problems cannot
    retroactively invalidate a successful device credential handoff.
    """
    from .owner import write_private

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", frame_id) or (
        not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id)
    ):
        return False
    pending_path = (
        service.settings.data_dir
        / "provisioning"
        / (frame_id + "." + session_id + ".pending.token")
    )
    target_path = service.settings.data_dir / "provisioning" / (frame_id + ".token")
    try:
        if pending_path.stat().st_size > 130:
            return False
        token = pending_path.read_text().strip()
        if not token or len(token) > 128:
            return False
        with service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = db.execute(
                "SELECT frame_id,evidence FROM recovery_sessions WHERE id=?", (session_id,)
            ).fetchone()
            current = db.execute("SELECT token_hash FROM frames WHERE id=?", (frame_id,)).fetchone()
            if (
                not session
                or session["frame_id"] != frame_id
                or not current
                or not (json.loads(session["evidence"]).get("binding_activated"))
                or not secrets.compare_digest(current["token_hash"], token_hash(token))
            ):
                return False
            write_private(target_path, token + "\n")
            pending_path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def device_headers(request):
    prefix = "x-emviary-recovery-"
    if not request.headers.get(prefix + "session"):
        return None
    return {
        "session_id": request.headers.get(prefix + "session"),
        "nonce": request.headers.get(prefix + "nonce", ""),
        "boot_id": request.headers.get(prefix + "boot", ""),
        "device_id": request.headers.get(prefix + "device-id", ""),
        "bundle_sha256": request.headers.get(prefix + "bundle-sha256", ""),
        "firmware": request.headers.get("x-firmware-version", ""),
    }


def install_routes(app, require, service, checked_form):
    sessions = RecoverySessions(service.store)
    app.state.recovery_sessions = sessions
    base = "/manage/usb-recovery/sessions/{identifier}"

    def response(value):
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @app.post(base)
    async def create(identifier: str, request: Request):
        from .usb_recovery import recovery_manifest

        data = await checked_form(request)
        return response(sessions.create(identifier, recovery_manifest(), data.get("device_id")))

    @app.get(base + "/{session_id}")
    def status(identifier: str, session_id: str, request: Request):
        require(request)
        return response(sessions.get(identifier, session_id))

    @app.post(base + "/{session_id}/renew")
    async def renew(identifier: str, session_id: str, request: Request):
        await checked_form(request)
        return response(sessions.renew(identifier, session_id))

    @app.post(base + "/{session_id}/boot")
    async def boot(identifier: str, session_id: str, request: Request):
        data = await checked_form(request)
        return response(sessions.transition_boot(identifier, session_id, data))

    @app.post(base + "/{session_id}/events")
    async def events(identifier: str, session_id: str, request: Request):
        data = await checked_form(request)
        checkpoint = {key: value for key, value in data.items() if key != "csrf"}
        if "elapsed_ms" in checkpoint:
            try:
                checkpoint["elapsed_ms"] = int(checkpoint["elapsed_ms"])
            except (ValueError, TypeError):
                raise HTTPException(400, "Invalid checkpoint timing") from None
        return response(sessions.event(identifier, session_id, checkpoint))

    @app.post(base + "/{session_id}/complete")
    async def complete(identifier: str, session_id: str, request: Request):
        data = await checked_form(request)
        proof_keys = ("boot_id", "image_id", "image_sha256")
        expected = (
            {key: data.get(key) for key in proof_keys}
            if any(key in data for key in proof_keys)
            else None
        )
        return response(
            sessions.finish(
                identifier, session_id, data.get("physical_confirmed") == "yes", expected=expected
            )
        )

    @app.post(base + "/{session_id}/cancel")
    async def cancel(identifier: str, session_id: str, request: Request):
        await checked_form(request)
        return response(sessions.finish(identifier, session_id, cancel=True))
