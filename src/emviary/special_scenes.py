"""Meaningful scene compositions, with explicit readable text constraints."""

import hashlib
import json
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin

ASSETS = Path(__file__).with_name("special_day_assets")


def scene_art(direction):
    name = "season" if direction == "season" else "memory"
    asset = ASSETS / (name + ".png")
    return dict(
        id="emviary-scene-" + name,
        asset=asset.name,
        common_name=("Winter light" if name == "season" else "Imagined canyon walk"),
        scientific_name="",
        approved=True,
        event_only=True,
        builtin_scene=True,
        kind="event",
        depicted_birds=0,
        months=list(range(1, 13)),
        license="MIT",
        source="Emviary AI-assisted scene study",
        source_url="emviary",
        asset_sha256=hashlib.sha256(asset.read_bytes()).hexdigest(),
    )


def text_lines(draw, text, font, width, maximum):
    lines, current = [], ""
    for word in text.split():
        if draw.textlength(word, font=font) > width:
            raise ValueError("A word is too wide. Shorten it or choose another composition.")
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > maximum:
        raise ValueError(
            "Use fewer words or choose Words beside the scene. Text will not be shrunk."
        )
    return lines


def scene_font(art_dir, size, serif=False):
    from .render import _font, _header_font

    selected = _font(art_dir, size) if serif else _header_font(size)
    # The approved proofs use BASIC. Make spacing independent of optional RAQM.
    return selected.font_variant(layout_engine=ImageFont.Layout.BASIC)


def validate_words(art_dir, day):
    if day.get("direction", "existing") == "existing":
        return
    side = day.get("composition") == "dedication"
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    text_lines(
        draw,
        day.get("heading") or day["label"],
        scene_font(art_dir, 32 if side else 30, serif=True),
        272 if side else 736,
        2 if side else 1,
    )
    text_lines(
        draw,
        day.get("message", ""),
        scene_font(art_dir, 24 if side else 22),
        272 if side else 736,
        2,
    )


def compose_scene(art_dir, artwork, plan, output, event_art_dir, neutral_output=None):
    day = plan["special_day"]
    validate_words(art_dir, day)
    root = (
        ASSETS
        if artwork.get("builtin_scene")
        else Path(event_art_dir)
        if artwork.get("event_only")
        else Path(art_dir)
    )
    path = (root / artwork["asset"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Artwork path is outside its library")
    if (
        artwork.get("asset_sha256")
        and hashlib.sha256(path.read_bytes()).hexdigest() != artwork["asset_sha256"]
    ):
        raise ValueError("Artwork does not match its reviewed image")
    if not artwork.get("approved"):
        raise ValueError("Choose approved artwork")
    side = day.get("composition") == "dedication"
    message = day.get("message", "")
    if side:
        box, x, width, ty, my = (24, 40, 456, 440), 630, 272, 154, 268
    else:
        box = (24, 20, 776, 390 if not message else 334)
        x, width, ty, my = 400, 736, 440 if not message else 364, 416
    canvas = Image.new("RGBA", (800, 480), "white")
    with Image.open(path) as original:
        picture = ImageOps.contain(
            original.convert("RGBA"), (box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS
        )
        canvas.alpha_composite(
            picture,
            (
                box[0] + (box[2] - box[0] - picture.width) // 2,
                box[1] + (box[3] - box[1] - picture.height) // 2,
            ),
        )
    draw = ImageDraw.Draw(canvas)
    for text, y, font in [
        (
            day.get("heading") or day["label"],
            ty,
            scene_font(art_dir, 32 if side else 30, serif=True),
        ),
        (message, my, scene_font(art_dir, 24 if side else 22)),
    ]:
        for n, line in enumerate(text_lines(draw, text, font, width, 2)):
            draw.text(
                (x, y + n * (37 if y == ty else 29)), line, font=font, anchor="mm", fill="black"
            )
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("eink_scene_paper_guard", "250:3")
    metadata.add_text(
        "eink_neutral_bands", json.dumps([] if side else [[334 if message else 400, 480]])
    )
    canvas.convert("RGB").save(output, pnginfo=metadata)
    if neutral_output:
        canvas.convert("RGB").save(neutral_output, pnginfo=metadata)


def editor_fields(day):
    direction = day.get("direction", "existing")

    def select(name, label, choices, selected):
        return (
            "<label>"
            + label
            + '<br><select name="'
            + name
            + '">'
            + "".join(
                '<option value="'
                + v
                + '"'
                + (" selected" if v == selected else "")
                + ">"
                + t
                + "</option>"
                for v, t in choices
            )
            + "</select></label>"
        )

    return (
        select(
            "direction",
            "Direction",
            [
                ("season", "Seasonal nature"),
                ("memory", "A personal memory"),
                ("existing", "Existing art & original layout"),
            ],
            direction,
        )
        + select(
            "composition",
            "Composition",
            [("scene", "Let the scene lead"), ("dedication", "Words beside the scene")],
            day.get("composition", "scene"),
        )
        + '<label>Heading for scene layouts<br><input name="heading" maxlength="40" value="'
        + escape(day.get("heading") or "", quote=True)
        + '" placeholder="Uses calendar name if empty"></label>'
        + (
            "<label>Memory note (only in management)<br><input "
            'name="memory_note" maxlength="300" value="'
        )
        + escape(day.get("memory_note", ""), quote=True)
        + '"></label>'
        + '<button type="button" class="secondary" data-scene-words>Use suggested words</button>'
        + (
            '<p class="quiet">Seasonal nature starts with winter light. '
            "Personal memories starts with an imagined canyon; "
            "choose your own uploaded art for a real place. All messages are editable. "
            "New layouts omit weather to give the scene room.</p>"
        )
    )
