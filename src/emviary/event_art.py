"""Owner-curated occasion art, deliberately separate from the bird catalog."""

import hashlib
import io
import json
import secrets
import warnings
from pathlib import Path

from PIL import Image, ImageOps

MAX_UPLOAD = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000


class EventArt:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "event-art"
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.json"

    def entries(self):
        return json.loads(self.manifest.read_text()) if self.manifest.exists() else []

    def path(self, entry):
        path = (self.root / entry["asset"]).resolve()
        if not path.is_relative_to(self.root.resolve()) or path.suffix != ".png":
            raise ValueError("Invalid event artwork path")
        return path

    def save(self, entries):
        temporary = self.root / ("manifest-" + secrets.token_hex(8) + ".tmp")
        try:
            temporary.write_text(json.dumps(entries, indent=2))
            temporary.replace(self.manifest)
        finally:
            temporary.unlink(missing_ok=True)

    def upload(self, raw, title, attribution):
        title, attribution = title.strip(), attribution.strip()
        if not title or len(title) > 80 or not attribution or len(attribution) > 300:
            raise ValueError("Enter an artwork title and its source or creator")
        if any(ord(c) < 32 for c in title + attribution):
            raise ValueError("Use single-line title and attribution")
        if not raw or len(raw) > MAX_UPLOAD:
            raise ValueError("Upload a PNG, JPEG or WebP image up to 10 MB")
        entries = self.entries()
        if len(entries) >= 200:
            raise ValueError("Remove an unused artwork before adding more than 200 images")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"}:
                        raise ValueError("Use PNG, JPEG or WebP")
                    if image.width * image.height > MAX_PIXELS or min(image.size) < 32:
                        raise ValueError(
                            "Image must be at least 32 pixels per side and below 20 MP"
                        )
                    if getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Use a still image")
                    image.load()
                    image = ImageOps.exif_transpose(image).convert("RGBA")
                    if not image.getchannel("A").getbbox():
                        raise ValueError("Image is entirely transparent")
                    image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                    encoded = io.BytesIO()
                    image.save(encoded, format="PNG")
        except (OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
            raise ValueError("Invalid or oversized image") from error
        identifier = "event-" + secrets.token_hex(8)
        asset = identifier + ".png"
        raw = encoded.getvalue()
        (self.root / asset).write_bytes(raw)
        entry = {
            "id": identifier,
            "asset": asset,
            "common_name": title,
            "scientific_name": "",
            "source": attribution,
            "source_url": "owner-upload",
            "license": "Owner-Provided",
            "approved": False,
            "event_only": True,
            "kind": "event",
            "depicted_birds": 0,
            "months": list(range(1, 13)),
            "asset_sha256": hashlib.sha256(raw).hexdigest(),
        }
        try:
            self.save([*entries, entry])
        except Exception:
            (self.root / asset).unlink(missing_ok=True)
            raise
        return entry

    def review(self, identifier, approved):
        entries = self.entries()
        entry = next((e for e in entries if e["id"] == identifier), None)
        if not entry:
            raise ValueError("Unknown event artwork")
        entry["approved"] = approved
        self.save(entries)

    def remove(self, identifier):
        entries = self.entries()
        entry = next((e for e in entries if e["id"] == identifier), None)
        if not entry:
            raise ValueError("Unknown event artwork")
        self.save([e for e in entries if e["id"] != identifier])
        self.path(entry).unlink(missing_ok=True)


def event_presets(group, year):
    from datetime import date, timedelta

    from .settings import SpecialDay

    if not 2020 <= year <= 2100:
        raise ValueError("Choose a year between 2020 and 2100")
    fixed = {
        "holidays": [
            (1, 1, "New Year's Day"),
            (2, 14, "Valentine's Day"),
            (3, 17, "St. Patrick's Day"),
            (6, 19, "Juneteenth"),
            (7, 4, "Independence Day"),
            (10, 31, "Halloween"),
            (11, 11, "Veterans Day"),
            (12, 24, "Christmas Eve"),
            (12, 25, "Christmas Day"),
            (12, 31, "New Year's Eve"),
        ],
        "seasons": [
            (3, 1, "First day of spring (meteorological)"),
            (6, 1, "First day of summer (meteorological)"),
            (9, 1, "First day of fall (meteorological)"),
            (12, 1, "First day of winter (meteorological)"),
        ],
    }
    if group not in fixed:
        raise ValueError("Choose holidays or seasons")
    dates = [(date(year, m, d), label, True) for m, d, label in fixed[group]]
    if group == "holidays":
        for month, weekday, ordinal, label in [
            (1, 0, 3, "Martin Luther King Jr. Day"),
            (2, 0, 3, "Presidents' Day"),
            (5, 6, 2, "Mother's Day"),
            (6, 6, 3, "Father's Day"),
            (9, 0, 1, "Labor Day"),
            (11, 3, 4, "Thanksgiving"),
        ]:
            first = date(year, month, 1)
            dates.append(
                (
                    first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (ordinal - 1)),
                    label,
                    False,
                )
            )
        last = date(year, 6, 1) - timedelta(days=1)
        dates.append((last - timedelta(days=last.weekday()), "Memorial Day", False))
    result = []
    for when, label, annual in dates:
        slug = "".join(c.lower() if c.isalnum() else "-" for c in label).strip("-")
        identifier = "preset-" + slug[:35] + ("" if annual else f"-{year}")
        result.append(
            SpecialDay(
                id=identifier, date=when.isoformat(), label=label, annual=annual, enabled=False
            ).model_dump()
        )
    return result


def import_presets(existing, group, year):
    result = list(existing)
    for entry in event_presets(group, year):
        if not any(
            e["id"] == entry["id"]
            or (
                e["label"] == entry["label"]
                and (
                    e["date"] == entry["date"]
                    or (e["annual"] and e["date"][5:] == entry["date"][5:])
                )
            )
            for e in result
        ):
            result.append(entry)
    return result
