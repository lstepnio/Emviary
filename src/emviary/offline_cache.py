"""Versioned, bounded offline metadata bound to immutable EPDGZ bytes.

Legacy clients receive exactly the existing body. Clients opt in with
X-Emviary-Offline-Version: 1. No additional request, render, or asset is needed.
"""

import base64
import gzip
import json
import re
import zlib

from .render import INK_CODES, RENDER_VERSION, season_for

HEADER_LIMIT = 4096
PATCH_COMPRESSED_LIMIT = 2048
PATCH_RAW_LIMIT = 65536


def offline_header(record):
    """Return admission metadata, or no header for legacy/unprovable content."""
    try:
        plan = json.loads(record["manifest"])
        artwork = plan.get("artworks", [plan["artwork"]])
        if (
            plan.get("special_day")
            or plan.get("special_day_test")
            or plan.get("content_category") == "special_day"
            or any(a.get("event_only") for a in artwork)
        ):
            return encode_header({"v": 1, "eligible": False})
        if plan.get("renderer_version") != RENDER_VERSION:
            return None
        panel = plan["policy"]["panel"]
        if (panel.get("width"), panel.get("height"), panel.get("orientation")) != (
            800,
            480,
            "landscape",
        ):
            return None
        patch = plan["offline_patch"]
        if not valid_patch(patch):
            return None
        digest = record["body_hash"]
        identifier = str(record["id"])
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not identifier.isdigit():
            return None
        season = (
            season_for(int(plan["local_date"][5:7]))
            if plan["policy"].get("seasonal_themes", True)
            else "evergreen"
        )
        return encode_header(
            {
                "v": 1,
                "id": identifier,
                "sha": digest,
                "eligible": True,
                "season": season,
                "patch": patch,
            }
        )
    except (ValueError, TypeError, KeyError, zlib.error):
        return None


def encode_header(value):
    encoded = base64.b64encode(json.dumps(value, separators=(",", ":")).encode()).decode("ascii")
    return encoded if len(encoded) <= HEADER_LIMIT else None


def valid_patch(patch):
    if not isinstance(patch, dict) or set(patch) != {"x", "y", "w", "h", "z"}:
        return False
    x, y, w, h = (patch[k] for k in ("x", "y", "w", "h"))
    if any(type(n) is not int for n in (x, y, w, h)):
        return False
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 800 or y + h > 480 or w % 2:
        return False
    expected = w * h // 2
    if expected > PATCH_RAW_LIMIT or not isinstance(patch["z"], str):
        return False
    if len(patch["z"]) > (PATCH_COMPRESSED_LIMIT + 2) // 3 * 4:
        return False
    compressed = base64.b64decode(patch["z"], validate=True)
    if len(compressed) > PATCH_COMPRESSED_LIMIT:
        return False
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, expected + 1)
    return (
        len(raw) == expected
        and decoder.eof
        and not decoder.unused_data
        and not decoder.unconsumed_tail
        and all((b >> 4) in INK_CODES and (b & 15) in INK_CODES for b in raw)
    )


def extract_patch(packed_path, x=200, y=10, w=580, h=36):
    """Extract exact palette indices from the weather-free converter result."""
    with gzip.open(packed_path, "rb") as reader:
        raw = reader.read(192001)
    if len(raw) != 192000:
        raise ValueError("Invalid neutral panel dimensions")
    tile = b"".join(raw[row * 400 + x // 2 : row * 400 + (x + w) // 2] for row in range(y, y + h))
    patch = {
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "z": base64.b64encode(zlib.compress(tile, 9)).decode("ascii"),
    }
    if not valid_patch(patch):
        raise ValueError("Offline tile exceeds bounded contract")
    return patch
