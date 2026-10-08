import gzip
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin

from .store import stable_json

RENDER_VERSION = 13
INK_CODES = {0, 1, 2, 3, 5, 6}


def profile_hash(policy, catalog):
    fields = {
        k: policy[k]
        for k in (
            "panel",
            "show_species_name",
            "show_location_name",
            "show_dated_weather_text",
            "weather_cues",
            "show_forecast_temperatures",
            "processing_preset",
            "dither_algorithm",
            "max_birds",
            "special_days",
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


def choose_art(
    artworks, local_date, inputs, recent_species, seed, recent_artworks=(), recent_styles=()
):
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
    variant_weights = []
    for artwork in variants:
        weight = 1.0
        if len(variants) > 1 and artwork["id"] in recent_artworks:
            weight *= 0.08
        if len({a.get("style") for a in variants}) > 1 and artwork.get("style") in recent_styles:
            weight *= 0.35
        variant_weights.append(weight)
    return rng.choices(variants, weights=variant_weights, k=1)[0]


def choose_artworks(
    artworks, local_date, inputs, recent_species, seed, policy, recent_manifests=()
):
    capacity = min(policy.get("max_birds", 3), 3)
    candidates = [a for a in artworks if a.get("depicted_birds", 1) <= capacity]
    recent_artworks = [a["id"] for m in recent_manifests for a in m.get("artworks", [m["artwork"]])]
    recent_styles = [
        a.get("style") for m in recent_manifests[:2] for a in m.get("artworks", [m["artwork"]])
    ]
    first = choose_art(
        candidates, local_date, inputs, recent_species, seed, recent_artworks, recent_styles
    )
    if (
        capacity < 2
        or first.get("kind", "cutout") != "cutout"
        or first.get("depicted_birds", 1) > 1
    ):
        return [first]
    selected = [first]
    capacity = min(capacity, first.get("composition_max_birds", 3))
    previous_count = (
        recent_manifests[0].get("layout", {}).get("bird_count") if recent_manifests else None
    )
    count_weights = [0.15 if n == previous_count else 1 for n in range(1, capacity + 1)]
    target = random.Random(seed + ":layout").choices(
        range(1, capacity + 1), weights=count_weights, k=1
    )[0]
    while len(selected) < target:
        alternatives = [
            a
            for a in candidates
            if a["scientific_name"] not in {b["scientific_name"] for b in selected}
            and a.get("kind", "cutout") == "cutout"
            and a.get("depicted_birds", 1) == 1
            and a.get("composition_max_birds", 3) >= target
            and compatible_licenses([*selected, a])
        ]
        try:
            selected.append(
                choose_art(
                    alternatives,
                    local_date,
                    inputs,
                    recent_species,
                    seed + f":bird-{len(selected)}",
                    recent_artworks,
                    recent_styles,
                )
            )
        except ValueError:
            break
    return selected


def artwork_aspect(art_dir, artwork):
    with Image.open(art_dir / artwork["asset"]) as image:
        box = image.convert("RGBA").getchannel("A").getbbox()
        if not box:
            raise ValueError("Artwork is entirely transparent")
        return (box[2] - box[0]) / (box[3] - box[1])


def choose_layout(artworks, seed, recent_manifests=(), art_dir=None):
    count = len(artworks)
    if artworks[0].get("kind") == "plate":
        return "plate"
    names = {
        1: ["solo", "solo-left", "solo-right"],
        2: ["pair", "lead-left-pair", "lead-right-pair"],
        3: ["trio", "lead-left-trio", "lead-right-trio", "center-lead-trio"],
    }[count]
    # Wide wings need the full width; never crop or mirror diagnostic plumage.
    if count == 1 and art_dir and artwork_aspect(art_dir, artworks[0]) > 1.6:
        return "solo"
    facing = artworks[0].get("facing")
    if facing in ("left", "right"):
        outward = "left" if facing == "left" else "right"
        names = [n for n in names if n != f"solo-{outward}" and not n.startswith(f"lead-{outward}")]
    previous = recent_manifests[0].get("layout", {}).get("name") if recent_manifests else None
    return random.Random(seed + ":composition").choice([n for n in names if n != previous] or names)


def composition_cells(name, count):
    """Nonoverlapping contain boxes and aligned caption columns on an 800x480 panel."""
    cells = {
        1: [(32, 48, 768, 376)],
        2: [(28, 48, 380, 376), (420, 48, 772, 376)],
        3: [(28, 48, 252, 376), (288, 48, 512, 376), (548, 48, 772, 376)],
    }[count]
    captions = {
        1: [(400, 700)],
        2: [(204, 350), (596, 350)],
        3: [(140, 224), (400, 224), (660, 224)],
    }[count]
    if name in ("solo-left", "solo-right"):
        cells = [(52, 48, 482, 376)] if name == "solo-left" else [(318, 48, 748, 376)]
    elif name in ("lead-left-pair", "lead-right-pair"):
        cells = [(28, 48, 472, 376), (500, 94, 772, 340)]
        captions = [(250, 440), (636, 272)]
    elif name in ("lead-left-trio", "lead-right-trio"):
        cells = [(28, 48, 356, 376), (388, 48, 568, 320), (596, 104, 776, 376)]
        captions = [(192, 328), (478, 180), (686, 180)]
    elif name == "center-lead-trio":
        cells = [(278, 48, 522, 376), (28, 94, 244, 348), (556, 94, 772, 348)]
        captions = [(400, 244), (136, 216), (664, 216)]
    if name in ("lead-right-pair", "lead-right-trio"):
        cells = [(800 - right, top, 800 - left, bottom) for left, top, right, bottom in cells]
        captions = [(800 - x, width) for x, width in captions]
    if name == "plate":
        cells = [(24, 48, 776, 376)]
    if name == "occasion":
        cells, captions = [(160, 55, 640, 323)], [(400, 700)]
    else:
        cells = [(left, top, right, bottom + 36) for left, top, right, bottom in cells]
    return cells, captions


def special_day_for(policy, local_date):
    # Stable list order resolves overlaps; leap-day events only match February 29.
    return next(
        (
            d
            for d in policy.get("special_days", [])
            if d["enabled"]
            and (d["date"][5:] == local_date[5:] if d["annual"] else d["date"] == local_date)
        ),
        None,
    )


def compatible_licenses(artworks):
    licenses = {a["license"] for a in artworks}
    return not {"CC-BY-SA-4.0", "CC-BY-NC-SA-4.0"} <= licenses


def composition_license(artworks):
    if not compatible_licenses(artworks):
        raise ValueError("Incompatible ShareAlike licenses in one composition")
    licenses = {a["license"] for a in artworks}
    for license_name in ("CC-BY-NC-SA-4.0", "CC-BY-SA-4.0"):
        if license_name in licenses:
            return license_name
    return "MIT"  # Our composition; original public-domain art stays public domain.


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
    if code in (95, 96, 97, 99):
        return "STORMS"
    if code >= 51 and values["precipitation_probability_max"] >= 50:
        return "RAIN"
    if values["wind_speed_10m_max"] >= 30:
        return "WINDY"
    code = int(values.get("daylight_weather_code", code))
    if code in (45, 48):
        return "FOG"
    return {0: "SUNNY", 1: "MOSTLY SUNNY", 2: "PARTLY SUNNY", 3: "OVERCAST"}.get(code, "OUTLOOK")


def forecast_temperatures(values):
    high = round(values["temperature_2m_max"] * 9 / 5 + 32)
    low = round(values["temperature_2m_min"] * 9 / 5 + 32)
    return f"H {high}° / L {low}°F"


def draw_weather_mark(draw, values, x, y):
    # Small, high-contrast ink strokes in the header, never pale filled clouds.
    label = weather_label(values)
    ink = "#333333"
    if label in ("SUNNY", "MOSTLY SUNNY", "PARTLY SUNNY"):
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


def wrapped_lines(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = ""
        for char in word:
            if line and draw.textlength(line + char, font=font) > width:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines


def fitted_lines(art_dir, draw, text, width, size, minimum, max_lines):
    for current in range(size, minimum - 1, -1):
        font = _font(art_dir, current)
        lines = wrapped_lines(draw, text, font, width)
        if len(lines) <= max_lines:
            return font, lines
    raise ValueError("Text is too long for a readable panel greeting or label")


def draw_occasion_art(draw, theme):
    # Hand-composed, bounded line art; no generated backgrounds or changes to the bird.
    ink = "#000000"
    for x in (105, 695):
        if theme == "birthday":
            draw.rectangle((x - 12, 105, x + 12, 125), outline=ink, width=2)
            draw.line((x - 14, 105, x + 14, 105), fill=ink, width=2)
            for dx in (-7, 0, 7):
                draw.line((x + dx, 95, x + dx, 102), fill=ink, width=2)
                draw.ellipse((x + dx - 1, 90, x + dx + 1, 93), fill="#92704a")
        elif theme == "anniversary":
            draw.ellipse((x - 15, 102, x + 3, 120), outline=ink, width=2)
            draw.ellipse((x - 3, 102, x + 15, 120), outline=ink, width=2)
        elif theme == "remembrance":
            draw.line((x - 7, 128, x + 7, 93), fill=ink, width=2)
            for dy in (0, 10, 20):
                draw.line((x - 4, 119 - dy, x - 12, 112 - dy), fill=ink, width=2)
        else:
            draw.rectangle((x - 12, 103, x + 12, 125), outline=ink, width=2)
            draw.line((x, 103, x, 125), fill=ink, width=2)
            draw.line((x - 12, 110, x + 12, 110), fill=ink, width=2)
            draw.arc((x - 12, 93, x, 105), 0, 300, fill=ink, width=2)
            draw.arc((x, 93, x + 12, 105), 240, 540, fill=ink, width=2)


def compose(art_dir, artwork, plan, output):
    date = plan["local_date"]
    season = season_for(int(date[5:7]))
    canvas = Image.new("RGBA", (800, 480), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((8, 8, 791, 471), outline="#333333", width=1)
    occasion = plan.get("special_day")
    draw.line(
        (20, 363 if occasion else 420, 780, 363 if occasion else 420), fill="#333333", width=1
    )
    palettes = {
        "winter": ("#829395", "#d1d9d5"),
        "spring": ("#6f805c", "#a9b482"),
        "summer": ("#718252", "#b6ba7c"),
        "autumn": ("#92704a", "#bbaa71"),
    }
    dark, light = palettes[season]
    seasonal_offset = -70 if occasion else 0
    # Marginal botanical motifs keep weather and season away from diagnostic plumage.
    for side in (1, -1) if plan["policy"].get("seasonal_themes", True) else ():
        x = 20 if side == 1 else 780
        draw.line(
            (x, 367 + seasonal_offset, x + side * 5, 288 + seasonal_offset), fill=dark, width=2
        )
        for n in range(4):
            y = 348 - n * 15 + seasonal_offset
            if season == "winter":
                draw.line((x + side * 3, y, x + side * 7, y - 7), fill=dark, width=1)
            else:
                draw.ellipse((x - 6, y - 11, x + 5, y - 4), fill=light)
                if season == "spring":
                    draw.ellipse((x - 2, y - 11, x + 3, y - 6), fill="#c1a96e")
    forecast = plan["inputs"].get("open_meteo")
    weather_valid = bool(forecast and forecast.get("local_date") == date)
    policy = plan["policy"]
    if weather_valid and policy["weather_cues"]:
        values = forecast["values"]
        label = weather_label(values)
        if not policy["show_dated_weather_text"]:
            draw_weather_mark(draw, values, 650, 25)
            draw.text((776, 18), label, font=_font(art_dir, 12), fill="#333333", anchor="ra")
            if policy.get("show_forecast_temperatures", True):
                draw.text(
                    (776, 34),
                    forecast_temperatures(values),
                    font=_font(art_dir, 12),
                    fill="#333333",
                    anchor="ra",
                )
    birds = plan.get("artworks", [artwork])
    count = sum(a.get("depicted_birds", 1) for a in birds)
    if not 1 <= count <= min(3, policy.get("max_birds", 3)):
        raise ValueError("The panel supports at most three birds")
    if any(a.get("kind", "cutout") != "cutout" for a in birds) and len(birds) != 1:
        raise ValueError("Historical plates require their own composition")
    if any(not a["approved"] or a.get("kind") == "field_study" for a in birds):
        raise ValueError("Reference artwork cannot be sent to the panel")
    composition_license(birds)
    if occasion and (len(birds) != 1 or count != 1):
        raise ValueError("Special-day greetings use one bird")
    layout_name = plan.get("layout", {}).get(
        "name", "solo" if len(birds) == 1 else "pair" if len(birds) == 2 else "trio"
    )
    cells, captions = composition_cells(layout_name, len(birds))
    if occasion:
        cells, captions = composition_cells("occasion", 1)
        draw_occasion_art(draw, occasion["theme"])
    for item, cell, caption in zip(birds, cells, captions, strict=True):
        left, top, right, bottom = cell
        center, width = caption
        with Image.open(art_dir / item["asset"]) as original:
            bird = original.convert("RGBA")
            box = bird.getchannel("A").getbbox()
            if not box:
                raise ValueError("Artwork is entirely transparent")
            bird = ImageOps.contain(
                bird.crop(box), (right - left, bottom - top), Image.Resampling.LANCZOS
            )
            x = left + (right - left - bird.width) // 2
            y = top + (bottom - top - bird.height) // 2
            canvas.alpha_composite(bird, (x, y))
        draw = ImageDraw.Draw(canvas)
        if policy["show_species_name"]:
            font, lines = fitted_lines(
                art_dir,
                draw,
                item["common_name"],
                width,
                24 if len(birds) == 1 else 19,
                17,
                2 if len(birds) > 1 else 1,
            )
            title_y = 346 if occasion else (434 if len(lines) == 2 else 445)
            for n, line in enumerate(lines):
                draw.text((center, title_y + n * 21), line, fill="#111111", font=font, anchor="mm")
    if occasion:
        font, lines = fitted_lines(art_dir, draw, occasion["label"], 660, 28, 18, 2)
        if len(lines) == 2:
            font, lines = fitted_lines(art_dir, draw, occasion["label"], 660, 20, 18, 2)
        for n, line in enumerate(lines):
            draw.text(
                (400, (378 if len(lines) == 2 else 389) + n * 22),
                line,
                fill="#111111",
                font=font,
                anchor="mm",
            )
        if occasion["message"]:
            font, lines = fitted_lines(art_dir, draw, occasion["message"], 660, 19, 14, 2)
            for n, line in enumerate(lines):
                draw.text(
                    (400, 422 + n * 21),
                    line,
                    fill="#333333",
                    font=font,
                    anchor="mm",
                )
    if policy.get("show_location_name", False):
        draw.text(
            (24, 20),
            plan.get("location_label", "COLORADO"),
            font=_font(art_dir, 12),
            fill="#333333",
        )
    if policy["show_dated_weather_text"] and weather_valid:
        v = forecast["values"]
        condition = weather_label(v) + " / " if policy["weather_cues"] else ""
        text = f"{condition}{v['temperature_2m_min']:.0f} to {v['temperature_2m_max']:.0f} C"
        draw.text((776, 25), text, font=_font(art_dir, 11), fill="#7c715d", anchor="ra")
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("eink_neutral_bands", json.dumps([[0, 48], [328 if occasion else 420, 480]]))
    canvas.convert("RGB").save(output, format="PNG", pnginfo=metadata)


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
    executable = os.getenv("EMVIARY_CONVERTER") or shutil.which("epaper-image-convert")
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
        "--color-method",
        "lab",
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
    preserve_neutral_graphics(source, target)
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


def preserve_neutral_graphics(source, target):
    # Text and fine rules should use black/white ink, not photo color diffusion.
    # These bands exclude all bird cells and seasonal botanical artwork.
    with Image.open(source) as image:
        if image.size != (800, 480):
            raise ValueError("Invalid source dimensions")
        pixels = image.convert("RGB").tobytes()
        bands = json.loads(image.info.get("eink_neutral_bands", "[[0,48],[420,480]]"))
        if any(
            not isinstance(b, list) or len(b) != 2 or not 0 <= b[0] < b[1] <= 480 for b in bands
        ):
            raise ValueError("Invalid neutral-graphics bands")
    with gzip.open(target, "rb") as handle:
        packed = bytearray(handle.read(192001))
    if len(packed) != 192000:
        raise ValueError("Invalid packed dimensions")
    for index in range(384000):
        x, y = index % 800, index // 800
        if not (any(start <= y < end for start, end in bands) or x < 12 or x >= 788):
            continue
        offset = index * 3
        r, g, b = pixels[offset : offset + 3]
        if max(r, g, b) - min(r, g, b) > 8:
            continue
        ink = 0 if (r + g + b) / 3 < 160 else 1
        byte = index // 2
        packed[byte] = (
            (packed[byte] & 0xF0) | ink if index % 2 else (packed[byte] & 15) | (ink << 4)
        )
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
