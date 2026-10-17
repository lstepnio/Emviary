"""Composition identity excludes forecast snapshots and rendering revisions."""

import hashlib
import json

from .store import stable_json


def composition_key(image_or_plan):
    plan = json.loads(image_or_plan["manifest"]) if "manifest" in image_or_plan else image_or_plan
    policy = plan.get("policy", {})
    artworks = plan.get("artworks") or [plan["artwork"]]
    occasion = plan.get("special_day") or {}
    fields = {
        "artworks": [
            {key: art.get(key) for key in ("id", "asset_sha256", "common_name")} for art in artworks
        ],
        "layout": plan.get("layout"),
        "occasion": {key: occasion.get(key) for key in ("label", "message", "theme")},
        "location": plan.get("location_label") if policy.get("show_location_name") else None,
        "appearance": {
            key: policy.get(key)
            for key in (
                "panel",
                "show_species_name",
                "show_location_name",
                "processing_preset",
                "dither_algorithm",
                "seasonal_themes",
            )
        },
        "season": ((int(plan["local_date"][5:7]) % 12) // 3)
        if policy.get("seasonal_themes", True)
        else None,
        "date": plan["local_date"] if policy.get("show_dated_weather_text") else None,
        "renderer": plan.get("renderer_version"),
    }
    return hashlib.sha256(stable_json(fields).encode()).hexdigest()


def distinct_compositions(images, *, exclude=(), limit=None):
    seen = set(exclude)
    result = []
    for image in images:
        key = composition_key(image)
        if key not in seen:
            seen.add(key)
            result.append(image)
            if limit is not None and len(result) >= limit:
                break
    return result
