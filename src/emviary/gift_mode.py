"""Explicit, durable gift packages, independent of the normal image queue."""

import hashlib
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import render
from .service import preparation_lock
from .store import RevisionConflict, stable_json

ASSETS = Path(__file__).with_name("gift_assets")
MAX_ASSET = 256 * 1024
WELCOME_HEADING = "A little nature, every day, for my love Emily."
WELCOME_HEADING_LIMIT = 60
ACTIVE = {"armed", "ready", "failed", "wrap_pending", "wrapped"}


def gift_text(value, limit, label):
    value = str(value).strip()
    if not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{label} needs 1–{limit} printable characters.")
    return value


def welcome_image(art_dir, values, output):
    """Native layout. Fit actual glyph widths; reject text that cannot fit."""

    def font(size, bold=False, italic=False):
        suffix = "-Bold" if bold else "-Italic" if italic else ""
        paths = [
            Path(f"/usr/share/fonts/truetype/dejavu/DejaVuSerif{suffix}.ttf"),
            Path(
                "/System/Library/Fonts/Supplemental/Georgia"
                + (" Bold" if bold else " Italic" if italic else "")
                + ".ttf"
            ),
        ]
        return next(
            (ImageFont.truetype(str(p), size) for p in paths if p.is_file()),
            render._font(art_dir, size, italic),
        )

    with Image.new("RGB", (800, 480), "white") as canvas:
        draw = ImageDraw.Draw(canvas)
        with Image.open(ASSETS / "chickadee.png") as source:
            bird = ImageOps.contain(source.convert("RGBA"), (260, 214))
            canvas.paste(bird, (182 - bird.width // 2, 32 + (214 - bird.height) // 2), bird)
        with Image.open(ASSETS / "homepage-qr.png") as qr:
            canvas.paste(qr, (182 - qr.width // 2, 248))
        draw.text((182, 448), "Scan for Emviary", font=font(16), fill="black", anchor="mt")
        groups = []
        for text, size, minimum, lines, bold, italic in (
            (values["heading"], 44, 32, 3, True, False),
            (values["message"], 25, 21, 3, False, False),
            (values["signature"], 24, 21, 1, False, True),
        ):
            if not text:
                continue
            width = 334 if italic else 360
            while size >= minimum:
                f = font(size, bold, italic)
                wrapped = render.wrapped_lines(draw, text, f, width)
                if len(wrapped) <= lines and all(
                    draw.textlength(t, font=f) <= width for t in wrapped
                ):
                    break
                size -= 1
            else:
                raise ValueError(
                    "This message is too long for the frame. Shorten it and preview again."
                )
            rows = [(line, draw.textbbox((0, 0), line, font=f)) for line in wrapped]
            height = sum(box[3] - box[1] for _, box in rows) + 12 * (len(rows) - 1)
            groups.append((f, rows, height, italic))
        total = sum(height for _, _, height, _ in groups) + 28 * (len(groups) - 1)
        if total > 320:
            raise ValueError("The dedication needs fewer lines to fit the frame.")
        y = (480 - total) // 2
        for f, rows, _, is_signature in groups:
            for line, box in rows:
                draw.text((370, y - box[1]), line, font=f, fill="black", stroke_width=0)
                if is_signature:
                    # A small solid mark survives native six-color conversion and
                    # does not depend on platform emoji fonts or variation selectors.
                    x = round(370 + draw.textlength(line, font=f) + 12)
                    top = round(y + (box[3] - box[1] - 15) / 2)
                    scale = 4
                    with Image.new("RGBA", (18 * scale, 16 * scale)) as heart:
                        h = ImageDraw.Draw(heart)
                        color = (190, 0, 0, 255)
                        h.ellipse((0, 0, 10 * scale, 10 * scale), fill=color)
                        h.ellipse((8 * scale, 0, 18 * scale - 1, 10 * scale), fill=color)
                        h.polygon(
                            [
                                (0, 5 * scale),
                                (18 * scale - 1, 5 * scale),
                                (9 * scale, 16 * scale - 1),
                            ],
                            fill=color,
                        )
                        mark = heart.resize((18, 16), Image.Resampling.LANCZOS)
                        canvas.paste(mark, (x, top), mark)
                y += box[3] - box[1] + 12
            y += 16
        canvas.save(output)


class GiftMode:
    def __init__(self, service):
        self.service = service
        self.root = service.settings.data_dir / "gifts"
        self.root.mkdir(exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError("Gift storage cannot be a symbolic link")
        with service.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS gift_packages (
                id TEXT PRIMARY KEY, frame_id TEXT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
                status TEXT NOT NULL, created_at TEXT NOT NULL, reported_at TEXT,
                values_json TEXT NOT NULL, assets_json TEXT NOT NULL, error TEXT NOT NULL DEFAULT ''
            )""")

    def current(self, frame_id):
        with self.service.store.connect() as db:
            row = db.execute(
                "SELECT * FROM gift_packages WHERE frame_id=? "
                "ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (frame_id,),
            ).fetchone()
        return dict(row) if row else None

    def get(self, frame_id, identifier):
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError("Unknown gift package")
        with self.service.store.connect() as db:
            row = db.execute(
                "SELECT * FROM gift_packages WHERE id=? AND frame_id=?", (identifier, frame_id)
            ).fetchone()
        if not row:
            raise ValueError("Unknown gift package")
        return dict(row)

    def path(self, packet, part, preview=False):
        if part not in {"welcome", "first"}:
            raise ValueError("Unknown gift image")
        if not re.fullmatch(r"[0-9a-f]{32}", packet["id"]):
            raise ValueError("Invalid gift package identifier")
        root = self.root / packet["id"]
        path = root / (part + (".jpg" if preview else ".epdgz"))
        if root.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError("Gift image is unavailable. Prepare the package again.")
        if not preview:
            spec = json.loads(packet["assets_json"])[part]
            if (
                path.stat().st_size != spec["size"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]
            ):
                raise ValueError("Gift image failed its integrity check. Prepare it again.")
        return path

    def sources(self, frame_id):
        with self.service.store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM images WHERE frame_id=? AND hidden=0 ORDER BY id DESC LIMIT 30",
                    (frame_id,),
                )
            ]

    def capable(self, frame_id):
        # Capability comes from authenticated telemetry, not a guessed version string.
        from .diagnostics import device_readings

        samples = device_readings(self.service.store, frame_id)
        return bool(samples and samples[-1]["metrics"].get("gift_version") in {1, 2})

    def wrap_capable(self, frame_id):
        from .diagnostics import device_readings

        samples = device_readings(self.service.store, frame_id)
        return bool(samples and samples[-1]["metrics"].get("gift_version") == 2)

    def prepare(self, frame_id, data):
        message = data.get("message", "").strip()
        values = {
            key: gift_text(data.get(key, ""), limit, label)
            for key, limit, label in (
                ("heading", WELCOME_HEADING_LIMIT, "Dedication"),
                ("signature", 30, "Signature"),
            )
        }
        values["message"] = gift_text(message, 80, "Message") if message else ""
        try:
            image_id = int(data.get("first_image_id", ""))
        except (ValueError, TypeError):
            raise ValueError("Choose the first composition.") from None
        with preparation_lock(self.service.settings.data_dir):
            current = self.current(frame_id)
            if current and current["status"] == "cancelled":
                raise RevisionConflict(
                    "Wait for the frame to receive cancellation before preparing another welcome."
                )
            if current and current["status"] in ACTIVE:
                raise RevisionConflict("Cancel the active gift before preparing another welcome.")
            choices = {row["id"]: row for row in self.sources(frame_id)}
            if image_id not in choices:
                raise ValueError("Choose an available composition for this frame.")
            with self.service.store.connect() as db:
                if (
                    db.execute(
                        "SELECT COUNT(*) FROM gift_packages WHERE frame_id=?", (frame_id,)
                    ).fetchone()[0]
                    >= 20
                ):
                    raise ValueError("This frame already has 20 gift packages.")
            self.service.store.frame(frame_id)
            plan = json.loads(choices[image_id]["manifest"])
            plan["inputs"] = {}
            for key in (
                "weather_cues",
                "show_weather_icon",
                "show_weather_condition",
                "show_forecast_temperatures",
                "show_dated_weather_text",
            ):
                plan["policy"][key] = False
            plan.pop("offline_patch", None)
            values["first_image_id"] = image_id
            identifier = uuid.uuid4().hex
            with tempfile.TemporaryDirectory(prefix=".gift-", dir=self.root) as temporary:
                root = Path(temporary)
                welcome_image(self.service.settings.art_dir, values, root / "welcome.png")
                render.compose(
                    self.service.settings.art_dir,
                    plan["artwork"],
                    plan,
                    root / "first.png",
                    self.service.event_art.root,
                )
                assets = {}
                for part in ("welcome", "first"):
                    packed, preview = root / (part + ".epdgz"), root / (part + ".jpg")
                    self.service.converter(
                        root / (part + ".png"),
                        packed,
                        preview,
                        plan["policy"],
                        self.service.settings.config.render.timeout_seconds,
                    )
                    digest = render.validate_epdgz(packed)
                    if not 0 < packed.stat().st_size <= MAX_ASSET:
                        raise ValueError("Gift image exceeds the device's bounded storage limit.")
                    with Image.open(preview) as im:
                        if im.size != (800, 480):
                            raise ValueError("Gift preview dimensions are invalid.")
                        im.verify()
                    assets[part] = {"sha256": digest, "size": packed.stat().st_size}
                (root / "first-plan.json").write_text(stable_json(plan))
                shutil.copytree(root, self.root / identifier)
            try:
                with self.service.store.connect() as db:
                    db.execute(
                        "INSERT INTO gift_packages(id,frame_id,status,created_at,"
                        "values_json,assets_json) "
                        "VALUES(?,?,'draft',?,?,?)",
                        (
                            identifier,
                            frame_id,
                            self.service.clock().isoformat(),
                            stable_json(values),
                            stable_json(assets),
                        ),
                    )
            except Exception:
                shutil.rmtree(self.root / identifier)
                raise
            return self.get(frame_id, identifier)

    def special_day_queue_notice(self, frame_id):
        packet = self.current(frame_id)
        state = packet["status"] if packet else None
        if state not in ACTIVE and state != "cancelled":
            return ""
        if state == "wrapped":
            return "The gift is ready to wrap. Preview Special Days here without opening the gift."
        if state == "cancelled":
            return "Wait for the frame to confirm gift cancellation before queuing a Special Day."
        return (
            "Gift setup is in progress. Once the welcome is on screen, the right white "
            "button opens the gift. Preview Special Days here and finish setup in Appearance."
        )

    def action(
        self,
        frame_id,
        identifier,
        action,
        display_confirmed=False,
        *,
        expected_state=None,
        cancel_confirmed=False,
    ):
        with preparation_lock(self.service.settings.data_dir):
            packet = self.get(frame_id, identifier)
            current = self.current(frame_id)
            if not current or current["id"] != identifier:
                raise RevisionConflict(
                    "This gift preview is out of date. Reload before continuing."
                )
            if action == "arm":
                if packet["status"] != "draft":
                    raise RevisionConflict("Prepare a new preview before arming this gift again.")
                if not self.capable(frame_id):
                    raise ValueError(
                        "Update the frame to gift-capable firmware and let it check in first."
                    )
                for part in ("welcome", "first"):
                    self.path(packet, part)
                status = "armed"
            elif action == "wrap":
                if packet["status"] != "ready":
                    raise RevisionConflict("Wait for the frame to report its welcome ready first.")
                if not display_confirmed:
                    raise ValueError("Confirm the welcome is displayed on the actual frame first.")
                if not self.wrap_capable(frame_id):
                    raise ValueError(
                        "Update the frame for power-on reveal and let it check in first."
                    )
                for part in ("welcome", "first"):
                    self.path(packet, part)
                status = "wrap_pending"
            elif action == "cancel":
                if expected_state != packet["status"] or expected_state not in ACTIVE:
                    raise RevisionConflict(
                        "Gift status changed. Review the current gift before cancelling."
                    )
                if expected_state in {"wrap_pending", "wrapped"} and not cancel_confirmed:
                    raise ValueError("Confirm that you want to cancel the power-on reveal.")
                status = "cancelled"
            else:
                raise ValueError("This gift action is not available.")
            with self.service.store.connect() as db:
                changed = db.execute(
                    "UPDATE gift_packages SET status=?,error='' WHERE id=? AND status=?",
                    (status, identifier, packet["status"]),
                )
                if changed.rowcount != 1:
                    raise RevisionConflict(
                        "Gift status changed. Review the current gift before continuing."
                    )
            return self.get(frame_id, identifier)

    def observe(self, frame_id, metrics):
        if not metrics or metrics.get("gift_version") not in {1, 2}:
            return
        packet = self.current(frame_id)
        if not packet or metrics.get("gift_id") != packet["id"]:
            return
        state = metrics.get("gift_state")
        allowed = {
            "armed": {"ready", "opened", "failed"},
            "ready": {"ready", "opened", "failed"},
            "failed": {"ready", "opened", "failed"},
            "wrap_pending": {"ready", "wrapped", "opened", "failed"},
            "wrapped": {"wrapped", "opened", "failed"},
            "cancelled": {"cancelled"},
        }
        if state not in allowed.get(packet["status"], set()):
            return
        if state == "wrapped" and metrics.get("gift_version") != 2:
            return
        status = (
            "wrap_pending" if packet["status"] == "wrap_pending" and state == "ready" else state
        )
        with self.service.store.connect() as db:
            db.execute(
                "UPDATE gift_packages SET status=?,reported_at=?,error=? WHERE id=? AND status=?",
                (
                    "cancelled_done" if state == "cancelled" else status,
                    self.service.clock().isoformat(),
                    metrics.get("gift_error", ""),
                    packet["id"],
                    packet["status"],
                ),
            )

    def payload(self, frame_id):
        packet = self.current(frame_id)
        if not packet or packet["status"] in {"draft", "opened", "cancelled_done"}:
            return {"version": 1, "state": "none"}
        value = {"version": 1, "id": packet["id"], "state": "cancelled"}
        if packet["status"] in {"wrap_pending", "wrapped"}:
            return {"version": 1, "id": packet["id"], "state": "wrapped"}
        if packet["status"] in ACTIVE:
            value.update(state="armed", hold_seconds=1800)
            for part in ("welcome", "first"):
                # Fail closed before offering any partial/corrupt package.
                self.path(packet, part)
                value[part] = {
                    **json.loads(packet["assets_json"])[part],
                    "url": (
                        f"{self.service.settings.config.public_base_url}/v1/gift/"
                        f"{packet['id']}/{part}"
                    ),
                }
        return value

    def verify_all(self):
        with self.service.store.connect() as db:
            packets = [dict(r) for r in db.execute("SELECT * FROM gift_packages")]
        for packet in packets:
            for part in ("welcome", "first"):
                render.validate_epdgz(self.path(packet, part))
                with Image.open(self.path(packet, part, True)) as im:
                    im.verify()
