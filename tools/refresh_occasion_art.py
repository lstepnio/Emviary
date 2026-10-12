"""Publish reviewed landscape replacements while preserving artwork IDs and calendar settings."""

import argparse
import hashlib
import json
from pathlib import Path

from emviary.service import Service, preparation_lock
from emviary.settings import FramePolicy


def refresh(service, source, review):
    source, review = Path(source), Path(review)
    manifest = json.loads((source / "manifest.json").read_text())
    proofs = {p["slug"]: p for p in json.loads((review / "review.json").read_text())}
    if not all(a.get("reviewed") for a in manifest["artworks"]):
        raise ValueError("Originals and panel proofs must be reviewed before publication")
    candidates = []
    for item in manifest["artworks"]:
        original = (source / item["asset"]).resolve()
        if not original.is_relative_to(source.resolve()):
            raise ValueError("Original outside collection")
        if hashlib.sha256(original.read_bytes()).hexdigest() != item["asset_sha256"]:
            raise ValueError("Original changed after review")
        proof = proofs[item["slug"]]
        if proof["source_asset_sha256"] != item["asset_sha256"]:
            raise ValueError("Proof does not match original")
        art = proof["normalized_art"]
        path = (review / "library" / "event-art" / art["asset"]).resolve()
        if not path.is_relative_to((review / "library" / "event-art").resolve()):
            raise ValueError("Reviewed asset outside library")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != art["asset_sha256"]:
            raise ValueError("Reviewed asset changed")
        candidates.append((item, art, raw))
    changed, added, event_changes = 0, 0, 0
    with preparation_lock(service.settings.data_dir):
        before = service.event_art.entries()
        entries = [dict(e) for e in before]
        for item, art, raw in candidates:
            existing = next((e for e in entries if e.get("generation_slug") == item["slug"]), None)
            if existing and existing.get("source_asset_sha256") == item["asset_sha256"]:
                continue
            identifier = existing["id"] if existing else art["id"]
            filename = identifier + "-landscape-" + art["asset_sha256"][:12] + ".png"
            path = service.event_art.root / filename
            if (
                path.exists()
                and hashlib.sha256(path.read_bytes()).hexdigest() != art["asset_sha256"]
            ):
                raise ValueError("Destination collision")
            path.write_bytes(raw)
            replacement = {
                **art,
                "id": identifier,
                "asset": filename,
                "approved": True,
                "generation_slug": item["slug"],
                "source_asset_sha256": item["asset_sha256"],
                "source_url": manifest["source_url"],
                "source": manifest["source"],
                "generation_method": manifest["generation_method"],
                "collection_version": 2,
                "art_direction": "Secular seasonal landscape; no ribbons or religious imagery",
            }
            if existing:
                existing.update(replacement)
                changed += 1
            else:
                entries.append(replacement)
                added += 1
        mapping = {e["generation_slug"]: e["id"] for e in entries if e.get("generation_slug")}
        frames, policies = [], []
        for frame in service.store.frames():
            policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
            for item in manifest["artworks"]:
                if not item.get("enabled") or not item.get("annual"):
                    continue
                day = next((d for d in policy["special_days"] if d["label"] == item["label"]), None)
                if day:
                    updated = {
                        **day,
                        "enabled": True,
                        "annual": True,
                        "artwork_id": mapping[item["slug"]],
                    }
                    if updated != day:
                        day.update(updated)
                        event_changes += 1
                else:
                    policy["special_days"].append(
                        {
                            "id": "preset-" + item["slug"],
                            "label": item["label"],
                            "date": item["representative_date"],
                            "enabled": True,
                            "annual": True,
                            "message": "",
                            "theme": "celebration",
                            "artwork_id": mapping[item["slug"]],
                        }
                    )
                    event_changes += 1
            validated = FramePolicy.model_validate(policy)
            frames.append(frame)
            policies.append(validated)
        # Files are ready before the single atomic library manifest publication.
        service.event_art.save(entries)
        try:
            with service.store.connect() as db:
                for frame, policy in zip(frames, policies, strict=True):
                    old = FramePolicy.model_validate_json(frame["policy"])
                    if old != policy:
                        updated = db.execute(
                            "UPDATE frames SET policy=?,config_revision=config_revision+1 "
                            "WHERE id=? AND config_revision=?",
                            (policy.model_dump_json(), frame["id"], frame["config_revision"]),
                        )
                        if updated.rowcount != 1:
                            raise RuntimeError(
                                "Frame settings changed concurrently; retry publication"
                            )
        except Exception:
            service.event_art.save(before)
            raise
    return {
        "artworks_replaced": changed,
        "artworks_added": added,
        "events_added_or_updated": event_changes,
        "collection_count": len(candidates),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    print(json.dumps(refresh(Service(), args.source, args.review)))
