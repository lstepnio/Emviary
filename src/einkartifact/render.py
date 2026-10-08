import gzip
import hashlib
import math
import os
import random
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .store import stable_json

RENDER_VERSION = 2
INK_CODES = {0, 1, 2, 3, 5, 6}


def profile_hash(policy, catalog):
    fields = {
        k: policy[k]
        for k in (
            "panel",
            "show_species_name",
            "show_dated_weather_text",
            "weather_cues",
            "processing_preset",
            "dither_algorithm",
            "max_birds",
            "allowed_species",
            "seasonal_themes",
        )
    }
    fields.update(renderer=RENDER_VERSION, catalog=catalog)
    return hashlib.sha256(stable_json(fields).encode()).hexdigest()


def season_for(month):
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def choose_art(artworks, local_date, inputs, recent_species, seed):
    month = int(local_date[5:7])
    eligible = [a for a in artworks if a["approved"] and month in a["months"]]
    if not eligible:
        raise ValueError("No approved seasonally eligible artwork")
    counts = {
        b["scientific_name"].casefold(): b["count"]
        for b in inputs.get("birdweather", {}).get("birds", [])
    }
    species = sorted({a["scientific_name"] for a in eligible})
    reported = {b["scientific_name"].casefold() for b in inputs.get("ebird", {}).get("birds", [])}
    weights = []
    for name in species:
        weight = 1 + 2 * math.log1p(min(counts.get(name.casefold(), 0), 100))
        if name.casefold() in reported:
            weight += 2  # Presence bonus, independent of individual or acoustic counts.
        if name in recent_species and len(species) > 1:
            weight *= 0.05
        weights.append(weight)
    rng = random.Random(seed)
    name = rng.choices(species, weights=weights, k=1)[0]
    variants = sorted((a for a in eligible if a["scientific_name"] == name), key=lambda a: a["id"])
    return rng.choice(variants)


def choose_artworks(artworks, local_date, inputs, recent_species, seed, policy):
    first = choose_art(artworks, local_date, inputs, recent_species, seed)
    capacity = min(policy.get("max_birds", 2), max(1, policy["panel"]["width"] // 360))
    alternatives = [a for a in artworks if a["scientific_name"] != first["scientific_name"]]
    if capacity < 2 or not alternatives or random.Random(seed + ":layout").random() < 0.35:
        return [first]
    try:
        second = choose_art(alternatives, local_date, inputs, recent_species, seed + ":second")
    except ValueError:
        return [first]
    return [first, second]


def _font(art_dir, size, italic=False):
    if italic:
        path = art_dir / "fonts/EBGaramond-Italic.ttf"
    else:
        path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")
        if not path.exists():
            path = art_dir / "fonts/EBGaramond-Italic.ttf"
    return ImageFont.truetype(str(path), size)


def weather_label(values):
    code = int(values["weather_code"])
    if code in (71, 73, 75, 77, 85, 86) and values["snowfall_sum"] > 0:
        return "SNOW"
    if code in (95, 96, 99):
        return "STORMS"
    if code >= 51 and values["precipitation_probability_max"] >= 50:
        return "RAIN"
    if values["wind_speed_10m_max"] >= 30:
        return "WINDY"
    if code in (45, 48):
        return "FOG"
    return {0: "CLEAR", 1: "MOSTLY CLEAR", 2: "PARTLY SUNNY", 3: "OVERCAST"}.get(code, "OUTLOOK")


def draw_weather_mark(draw, values, x, y):
    # Small, high-contrast ink strokes in the header, never pale filled clouds.
    label = weather_label(values)
    ink = "#333333"
    if label in ("CLEAR", "MOSTLY CLEAR", "PARTLY SUNNY"):
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), outline=ink, width=2)
        for angle in range(0, 360, 45):
            theta = math.radians(angle)
            draw.line(
                (
                    x + round(7 * math.cos(theta)),
                    y + round(7 * math.sin(theta)),
                    x + round(10 * math.cos(theta)),
                    y + round(10 * math.sin(theta)),
                ),
                fill=ink,
                width=2,
            )
        if label == "PARTLY SUNNY":
            draw.line((x - 10, y + 12, x + 10, y + 12), fill=ink, width=2)
    elif label in ("RAIN", "STORMS"):
        for offset in (-8, 0, 8):
            draw.line((x + offset + 2, y - 6, x + offset - 2, y + 6), fill=ink, width=2)
    elif label == "SNOW":
        for angle in (0, 60, 120):
            theta = math.radians(angle)
            dx, dy = round(8 * math.cos(theta)), round(8 * math.sin(theta))
            draw.line((x - dx, y - dy, x + dx, y + dy), fill=ink, width=2)
    elif label == "WINDY":
        for offset in (-5, 3):
            draw.line((x - 11, y + offset, x + 5, y + offset), fill=ink, width=2)
            draw.arc((x + 1, y + offset - 6, x + 11, y + offset), 180, 360, fill=ink, width=2)
    else:
        for offset, halfwidth in ((-6, 9), (0, 12), (6, 8)):
            draw.line((x - halfwidth, y + offset, x + halfwidth, y + offset), fill=ink, width=2)


def compose(art_dir, artwork, plan, output):
    date = plan["local_date"]
    season = season_for(int(date[5:7]))
    canvas = Image.new("RGBA", (800, 480), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((22, 22, 778, 458), outline="#c2b59a", width=1)
    draw.line((50, 392, 750, 392), fill="#cbbd9e", width=1)
    palettes = {
        "winter": ("#829395", "#d1d9d5"),
        "spring": ("#6f805c", "#a9b482"),
        "summer": ("#718252", "#b6ba7c"),
        "autumn": ("#92704a", "#bbaa71"),
    }
    dark, light = palettes[season]
    # Marginal botanical motifs keep weather and season away from diagnostic plumage.
    for side in (1, -1) if plan["policy"].get("seasonal_themes", True) else ():
        x = 57 if side == 1 else 743
        draw.line((x, 367, x + side * 9, 288), fill=dark, width=2)
        for n in range(4):
            y = 348 - n * 15
            if season == "winter":
                draw.line((x + side * 3, y, x + side * 13, y - 7), fill=dark, width=1)
            else:
                draw.ellipse((x - 8, y - 11, x + 7, y - 4), fill=light)
                if season == "spring":
                    draw.ellipse((x - 2, y - 11, x + 3, y - 6), fill="#c1a96e")
    forecast = plan["inputs"].get("open_meteo")
    weather_valid = bool(forecast and forecast.get("local_date") == date)
    policy = plan["policy"]
    if weather_valid and policy["weather_cues"]:
        values = forecast["values"]
        label = weather_label(values)
        if not policy["show_dated_weather_text"]:
            draw_weather_mark(draw, values, 617, 39)
            draw.text((746, 39), label, font=_font(art_dir, 12), fill="#333333", anchor="ra")
    birds = plan.get("artworks", [artwork])
    if not 1 <= len(birds) <= min(2, policy.get("max_birds", 2)):
        raise ValueError("The panel supports at most two birds")
    centers = [400] if len(birds) == 1 else [222, 578]
    limits = (572, 313) if len(birds) == 1 else (302, 285)
    for item, center in zip(birds, centers, strict=True):
        with Image.open(art_dir / item["asset"]) as original:
            bird = original.convert("RGBA")
            box = bird.getchannel("A").getbbox()
            if not box:
                raise ValueError("Artwork is entirely transparent")
            bird = ImageOps.contain(bird.crop(box), limits, Image.Resampling.LANCZOS)
            x = center - bird.width // 2
            y = 69 + (285 - bird.height) // 2 if len(birds) == 2 else 55 + (313 - bird.height) // 2
            canvas.alpha_composite(bird, (x, y))
        draw = ImageDraw.Draw(canvas)
        if policy["show_species_name"]:
            title = item["common_name"]
            font = _font(art_dir, 24 if len(birds) == 1 else 19)
            width = 650 if len(birds) == 1 else 322
            while draw.textlength(title, font=font) > width and font.size > 17:
                font = _font(art_dir, font.size - 1)
            if draw.textlength(title, font=font) > width:
                raise ValueError("Species title cannot be legible in this layout")
            draw.text((center, 415), title, fill="#111111", font=font, anchor="mm")
            draw.text(
                (center, 442),
                item["scientific_name"],
                fill="#333333",
                font=_font(art_dir, 17 if len(birds) == 1 else 14, italic=True),
                anchor="mm",
            )
    # Dating every composition also makes stale retained weather cues understandable.
    draw.text((53, 39), f"DENVER  /  {date}", font=_font(art_dir, 12), fill="#333333")
    if policy["show_dated_weather_text"] and weather_valid:
        v = forecast["values"]
        condition = weather_label(v) + " / " if policy["weather_cues"] else ""
        text = f"{condition}{v['temperature_2m_min']:.0f} to {v['temperature_2m_max']:.0f} C"
        draw.text((746, 39), text, font=_font(art_dir, 11), fill="#7c715d", anchor="ra")
    canvas.convert("RGB").save(output, format="PNG")


def validate_epdgz(path, width=800, height=480):
    path = Path(path)
    if not 16 <= path.stat().st_size <= 1_000_000:
        raise ValueError("Invalid EPDGZ file size")
    expected = width * height // 2
    with gzip.open(path, "rb") as reader:
        raw = reader.read(expected + 1)
    if len(raw) != expected:
        raise ValueError("EPDGZ decompressed dimensions do not match the panel")
    if any((b >> 4) not in INK_CODES or (b & 15) not in INK_CODES for b in raw):
        raise ValueError("EPDGZ contains unsupported panel color indices")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def convert(source, target, preview, policy, timeout):
    executable = os.getenv("EINK_CONVERTER") or shutil.which("epaper-image-convert")
    if not executable:
        local = Path("converter/node_modules/.bin/epaper-image-convert").resolve()
        if local.exists():
            executable = str(local)
    if not executable:
        raise RuntimeError("The pinned epaper-image-convert CLI is not installed")
    args = [
        executable,
        str(source),
        str(target),
        "-f",
        "epdgz",
        "-d",
        "800x480",
        "--palette-preset",
        "spectra6",
        "-p",
        policy["processing_preset"],
        "--dither-algorithm",
        policy["dither_algorithm"],
        "-t",
        str(preview),
        "--thumbnail-max-dimension",
        "800",
    ]
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        # Do not echo arbitrary external process output into public responses or secrets.
        raise RuntimeError(f"Image converter exited with status {result.returncode}")
    validate_epdgz(target)
    preserve_paper_white(source, target)
    digest = validate_epdgz(target)
    panel_preview(target, preview)
    return digest


def preserve_paper_white(source, target):
    # Palette tone adjustment can dither even untouched white paper into
    # colored speckles. Keep exactly white source pixels as the panel's white
    # ink. Colored art, antialiasing and decorative marks retain conversion.
    with Image.open(source) as image:
        if image.size != (800, 480):
            raise ValueError("Invalid source dimensions")
        pixels = image.convert("RGB").tobytes()
    with gzip.open(target, "rb") as handle:
        packed = bytearray(handle.read(192001))
    if len(packed) != 192000:
        raise ValueError("Invalid packed dimensions")
    for index in range(384000):
        offset = index * 3
        if pixels[offset : offset + 3] == b"\xff\xff\xff":
            byte = index // 2
            packed[byte] = (packed[byte] & 0xF0) | 1 if index % 2 else (packed[byte] & 15) | 16
    Path(target).write_bytes(gzip.compress(bytes(packed), mtime=0))


def panel_preview(target, preview):
    # Spectra6 perceived values from the pinned converter palette. This shows
    # the actual packed pixel choices; ambient lighting still affects the panel.
    colors = {
        0: (2, 2, 2),
        1: (190, 200, 200),
        2: (205, 202, 0),
        3: (135, 19, 0),
        5: (5, 64, 158),
        6: (39, 102, 60),
    }
    with gzip.open(target, "rb") as handle:
        packed = handle.read(192001)
    if len(packed) != 192000:
        raise ValueError("Invalid packed preview dimensions")
    indices = bytes(n for byte in packed for n in (byte >> 4, byte & 15))
    if set(indices) - INK_CODES:
        raise ValueError("Invalid packed preview colors")
    image = Image.frombytes("P", (800, 480), indices)
    palette = [channel for n in range(256) for channel in colors.get(n, (0, 0, 0))]
    image.putpalette(palette)
    image.convert("RGB").save(preview, "JPEG", quality=95, subsampling=0)
