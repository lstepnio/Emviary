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

RENDER_VERSION = 1
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
    weights = []
    for name in species:
        weight = 1 + 2 * math.log1p(min(counts.get(name.casefold(), 0), 100))
        if name in recent_species and len(species) > 1:
            weight *= 0.05
        weights.append(weight)
    rng = random.Random(seed)
    name = rng.choices(species, weights=weights, k=1)[0]
    variants = sorted((a for a in eligible if a["scientific_name"] == name), key=lambda a: a["id"])
    return rng.choice(variants)


def _font(art_dir, size, italic=False):
    if italic:
        path = art_dir / "fonts/EBGaramond-Italic.ttf"
    else:
        path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")
        if not path.exists():
            path = art_dir / "fonts/EBGaramond-Italic.ttf"
    return ImageFont.truetype(str(path), size)


def compose(art_dir, artwork, plan, output):
    date = plan["local_date"]
    season = season_for(int(date[5:7]))
    rng = random.Random(plan["seed"])
    canvas = Image.new("RGBA", (800, 480), "#f3eddd")
    draw = ImageDraw.Draw(canvas)
    # Sparse paper texture avoids a flat digital background without busy dithering.
    for _ in range(3000):
        x, y = rng.randrange(800), rng.randrange(480)
        draw.point((x, y), fill=rng.choice(["#ebe4d2", "#f0e9d8", "#f7f1e3"]))
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
    for side in (1, -1):
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
        code = int(values["weather_code"])
        if code >= 2:
            for n in range(3):
                draw.ellipse((595 + n * 23, 60 - n * 5, 648 + n * 23, 78), fill="#d6d9cd")
        if code in (71, 73, 75, 77, 85, 86) and values["snowfall_sum"] > 0:
            for x, y in [(630, 99), (681, 104), (656, 126)]:
                draw.line((x - 3, y, x + 3, y), fill="#839496", width=1)
                draw.line((x, y - 3, x, y + 3), fill="#839496", width=1)
        elif values["precipitation_probability_max"] >= 50 and code >= 51:
            for n in range(4):
                x = 612 + n * 24
                draw.line((x, 95, x - 5, 108), fill="#8b9d9b", width=1)
        if values["wind_speed_10m_max"] >= 30:
            draw.arc((584, 135, 689, 153), 180, 335, fill="#929b89", width=1)
            draw.arc((610, 151, 707, 166), 190, 340, fill="#929b89", width=1)
    with Image.open(art_dir / artwork["asset"]) as original:
        bird = original.convert("RGBA")
        box = bird.getchannel("A").getbbox()
        if not box:
            raise ValueError("Artwork is entirely transparent")
        bird = ImageOps.contain(bird.crop(box), (572, 313), Image.Resampling.LANCZOS)
        x = (800 - bird.width) // 2 + rng.choice([-12, 0, 12])
        y = 55 + (313 - bird.height) // 2
        canvas.alpha_composite(bird, (x, y))
    draw = ImageDraw.Draw(canvas)
    ink = "#413e35"
    if policy["show_species_name"]:
        title = artwork["common_name"]
        font = _font(art_dir, 24)
        while draw.textlength(title, font=font) > 650:
            font = _font(art_dir, font.size - 1)
        draw.text((400, 415), title, fill=ink, font=font, anchor="mm")
        draw.text(
            (400, 442),
            artwork["scientific_name"],
            fill="#70664f",
            font=_font(art_dir, 17, italic=True),
            anchor="mm",
        )
    # Dating every composition also makes stale retained weather cues understandable.
    draw.text((53, 39), f"DENVER  /  {date}", font=_font(art_dir, 12), fill="#7c715d")
    if policy["show_dated_weather_text"] and weather_valid:
        v = forecast["values"]
        text = f"OUTLOOK {date}: {v['temperature_2m_min']:.0f} to {v['temperature_2m_max']:.0f} C"
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
    return validate_epdgz(target)
