"""Occasional locality-matched wildlife, independent of bird observation feeds."""

import calendar
import hashlib
from datetime import date

from .event_art import special_day_date


def wildlife_dates(frame_id, year, month, policy):
    """One stable surprise in each half-month; enabled special days take precedence."""
    if policy.get("wildlife_per_month", 0) != 2:
        return []
    blocked = {
        special_day_date(day, year)
        for day in policy.get("special_days", [])
        if day.get("enabled", True)
    }
    result = []
    last = calendar.monthrange(year, month)[1]
    for start, end in ((1, 14), (15, last)):
        choices = [date(year, month, n) for n in range(start, end + 1)]
        choices = [when for when in choices if when not in blocked]
        if choices:
            seed = hashlib.sha256(f"wildlife:{frame_id}:{year}:{month}:{start}".encode()).digest()
            result.append(choices[int.from_bytes(seed[:8], "big") % len(choices)].isoformat())
    return result


def region_for_site(site):
    """Colorado state scope or a local location actually inside Colorado's bounds."""
    location = site.weather_location
    if site.bird_area == "colorado" or (
        37 <= location.latitude <= 41 and -109.05 <= location.longitude <= -102.04
    ):
        return "US-CO"
    return None


def eligible_wildlife(artworks, site, local_date):
    region = region_for_site(site)
    month = int(local_date[5:7])
    return [
        a
        for a in artworks
        if a.get("category") == "wildlife"
        and a["approved"]
        and region in a.get("regions", [])
        and month in a["months"]
    ]


def choose_wildlife(artworks, seed, recent_manifests):
    """Cycle species before repeating; bird reports never rank mammals."""
    last_seen = {}
    for index, manifest in enumerate(recent_manifests):
        for art in manifest.get("artworks", [manifest["artwork"]]):
            if art.get("category") == "wildlife":
                last_seen.setdefault(art["scientific_name"], index)
    fresh = [a for a in artworks if a["scientific_name"] not in last_seen]
    if not fresh:
        oldest = max(last_seen[a["scientific_name"]] for a in artworks)
        fresh = [a for a in artworks if last_seen[a["scientific_name"]] == oldest]
    choices = sorted(fresh, key=lambda a: a["id"])
    return choices[int(seed[:16], 16) % len(choices)]
