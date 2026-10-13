"""Owner-curated occasion art, deliberately separate from the bird catalog."""

import hashlib
import io
import json
import secrets
import warnings
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageOps

MAX_UPLOAD = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000

MOVABLE_PRESETS = [
    (1, 0, 3, "Martin Luther King Jr. Day"),
    (2, 0, 3, "Presidents' Day"),
    (5, 6, 2, "Mother's Day"),
    (6, 6, 3, "Father's Day"),
    (9, 0, 1, "Labor Day"),
    (11, 3, 4, "Thanksgiving"),
    (5, 0, -1, "Memorial Day"),
]


def weekday_date(year, rule):
    month, weekday, ordinal = rule["month"], rule["weekday"], rule["ordinal"]
    if ordinal == -1:
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (ordinal - 1))


def legacy_preset_recurrence(entry):
    """Only infer recurrence for an unchanged, recognizable dated preset."""
    if entry.get("annual", True):
        return None
    for month, weekday, ordinal, label in MOVABLE_PRESETS:
        slug = "".join(c.lower() if c.isalnum() else "-" for c in label).strip("-")
        prefix = "preset-" + slug[:35] + "-"
        identifier = entry.get("id", "")
        if not identifier.startswith(prefix) or entry.get("label") != label:
            continue
        suffix = identifier[len(prefix) :]
        if not suffix.isdigit() or not 2020 <= int(suffix) <= 2100:
            continue
        rule = dict(kind="nth_weekday", month=month, weekday=weekday, ordinal=ordinal)
        if entry.get("date") == weekday_date(int(suffix), rule).isoformat():
            return rule
    return None


def preset_calendar_rule(entry):
    """Recognize original preset dates, including the old fixed-repeat mistake.

    Custom IDs, headings and deliberately changed dates are not normalized.
    """
    for month, weekday, ordinal, label in MOVABLE_PRESETS:
        slug = "".join(c.lower() if c.isalnum() else "-" for c in label).strip("-")
        base = "preset-" + slug[:35]
        identifier = entry.get("id", "")
        if entry.get("label") != label:
            continue
        if identifier != base:
            suffix = identifier.removeprefix(base + "-")
            if not identifier.startswith(base + "-") or not suffix.isdigit():
                continue
            if not 2020 <= int(suffix) <= 2100:
                continue
        rule = dict(kind="nth_weekday", month=month, weekday=weekday, ordinal=ordinal)
        original = date.fromisoformat(entry["date"])
        if original == weekday_date(original.year, rule):
            return rule
    return None


def normalize_preset_calendar(entries):
    """Merge equivalent dated presets, retaining settings and original survivor ID.

    Different artwork, greetings, themes or priorities remain distinct. An enabled
    copy keeps the merged holiday enabled. This is explicit cleanup, not a read-time
    migration of user-customized dates.
    """
    result, positions = [], {}
    for entry in entries:
        rule = preset_calendar_rule(entry)
        normalized = {**entry, "annual": True, "recurrence": rule} if rule else dict(entry)
        if not rule:
            result.append(normalized)
            continue
        key = json.dumps(
            {k: v for k, v in normalized.items() if k not in {"id", "date", "enabled"}},
            sort_keys=True,
        )
        if key in positions:
            survivor = result[positions[key]]
            survivor["enabled"] = survivor.get("enabled", True) or entry.get("enabled", True)
        else:
            positions[key] = len(result)
            result.append(normalized)
    return result


def special_day_date(entry, year):
    if entry.get("recurrence"):
        return weekday_date(year, entry["recurrence"])
    original = date.fromisoformat(entry["date"])
    if not entry.get("annual", True):
        return original if original.year == year else None
    try:
        return original.replace(year=year)
    except ValueError:
        return None


def next_special_day_date(entry, today):
    for year in range(today.year, min(today.year + 9, 10000)):
        when = special_day_date(entry, year)
        if when is not None and when >= today:
            return when
    return date.fromisoformat(entry["date"])


def effective_special_days(entries, year):
    """Keep saved entries, but collapse identical dated copies of known presets.

    A changed greeting, artwork or setting remains a separate event. The original
    group position preserves precedence; the closest original year supplies its
    representative entry.
    """
    groups, positions = {}, []
    for entry in entries:
        inferred = preset_calendar_rule(entry)
        if inferred and inferred == entry.get("recurrence"):
            key = json.dumps(
                {k: v for k, v in entry.items() if k not in {"id", "date"}}, sort_keys=True
            )
        else:
            key = "id:" + entry["id"]
        if key not in groups:
            groups[key] = []
            positions.append(key)
        groups[key].append(entry)
    return [min(groups[key], key=lambda e: abs(year - int(e["date"][:4]))) for key in positions]


def special_day_conflicts(entries, today, years=5):
    """Preview all overlaps in the next five years using the runtime precedence."""
    by_date = {}
    for year in range(today.year, min(today.year + years, 10000)):
        for entry in effective_special_days(entries, year):
            if not entry.get("enabled", True):
                continue
            when = special_day_date(entry, year)
            if when is not None and when >= today:
                by_date.setdefault(when, []).append(entry)
    return [
        (when, sorted(matches, key=lambda e: -e.get("priority", 0)))
        for when, matches in sorted(by_date.items())
        if len(matches) > 1
    ]


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
            "approved": True,
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

    def approve_existing(self):
        """One-time compatibility migration for uploads from the manual review workflow."""
        entries = self.entries()
        if any(not e.get("approved") for e in entries):
            for entry in entries:
                entry["approved"] = True
            self.save(entries)

    def remove(self, identifier):
        entries = self.entries()
        entry = next((e for e in entries if e["id"] == identifier), None)
        if not entry:
            raise ValueError("Unknown event artwork")
        self.save([e for e in entries if e["id"] != identifier])
        self.path(entry).unlink(missing_ok=True)


def event_presets(group, year):
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
    dates = [(date(year, m, d), label, None) for m, d, label in fixed[group]]
    if group == "holidays":
        for month, weekday, ordinal, label in MOVABLE_PRESETS:
            rule = dict(kind="nth_weekday", month=month, weekday=weekday, ordinal=ordinal)
            dates.append((weekday_date(year, rule), label, rule))
    result = []
    for when, label, rule in dates:
        slug = "".join(c.lower() if c.isalnum() else "-" for c in label).strip("-")
        result.append(
            SpecialDay(
                id="preset-" + slug[:35],
                date=when.isoformat(),
                label=label,
                annual=True,
                recurrence=rule,
                enabled=False,
            ).model_dump()
        )
    return result


def import_presets(existing, group, year):
    result = normalize_preset_calendar(existing)
    for entry in event_presets(group, year):
        if not any(
            e["id"] == entry["id"]
            or (
                entry.get("recurrence")
                and (e.get("recurrence") or legacy_preset_recurrence(e)) == entry["recurrence"]
                and e["label"] == entry["label"]
            )
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
