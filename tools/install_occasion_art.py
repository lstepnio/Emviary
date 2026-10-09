"""Install a reviewed occasion collection without changing event enablement or bird rotation."""

import argparse
import hashlib
import json
from pathlib import Path

from emviary import render
from emviary.event_art import EventArt
from emviary.service import Service, preparation_lock
from emviary.settings import FramePolicy


def collection(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    labels, slugs = set(), set()
    for entry in manifest["artworks"]:
        path = (root / entry["asset"]).resolve()
        if not path.is_relative_to(root) or path.suffix != ".png":
            raise ValueError("Invalid collection asset")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["asset_sha256"]:
            raise ValueError("Collection asset digest changed")
        if entry["label"] in labels or entry["slug"] in slugs:
            raise ValueError("Duplicate occasion in collection")
        labels.add(entry["label"])
        slugs.add(entry["slug"])
    return manifest


def stage(service, root, review_dir, frame_id):
    manifest = collection(root)
    review_dir = Path(review_dir)
    library = EventArt(review_dir)
    policy = FramePolicy.model_validate_json(service.store.frame(frame_id)["policy"]).model_dump()
    results = []
    for item in manifest["artworks"]:
        art = library.upload(
            (Path(root) / item["asset"]).read_bytes(), item["label"], manifest["source"]
        )
        art["approved"] = True  # Only this isolated review copy is eligible for preview.
        slug = item["slug"]
        master, packed, preview = (
            review_dir / (slug + suffix) for suffix in (".png", ".epdgz", ".jpg")
        )
        plan = {
            "local_date": item["representative_date"],
            "inputs": {},
            "policy": policy,
            "artworks": [art],
            "special_day": {
                "label": item["label"],
                "message": "",
                "theme": "celebration",
                "artwork_id": art["id"],
            },
        }
        render.compose(service.settings.art_dir, art, plan, master, library.root)
        service.converter(
            master, packed, preview, policy, service.settings.config.render.timeout_seconds
        )
        digest = render.validate_epdgz(packed)
        results.append(
            {
                "slug": slug,
                "label": item["label"],
                "packed_sha256": digest,
                "preview": preview.name,
                "renderer_version": render.RENDER_VERSION,
            }
        )
        print("Validated panel preview: " + item["label"], flush=True)
    (review_dir / "review.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def install(service, root):
    manifest = collection(root)
    if not all(e.get("reviewed") for e in manifest["artworks"]):
        raise ValueError("Review the generated art and panel previews before installation")
    mappings = {}
    added, assigned = 0, 0
    with preparation_lock(service.settings.data_dir):
        for item in manifest["artworks"]:
            existing = next(
                (
                    e
                    for e in service.event_art.entries()
                    if e.get("generation_slug") == item["slug"]
                    and e.get("source_asset_sha256") == item["asset_sha256"]
                ),
                None,
            )
            if existing:
                art = existing
            else:
                art = service.event_art.upload(
                    (Path(root) / item["asset"]).read_bytes(), item["label"], manifest["source"]
                )
                entries = service.event_art.entries()
                next(e for e in entries if e["id"] == art["id"]).update(
                    generation_slug=item["slug"],
                    source_asset_sha256=item["asset_sha256"],
                    source_url=manifest["source_url"],
                    generation_method=manifest["generation_method"],
                )
                service.event_art.save(entries)
                added += 1
            service.event_art.review(art["id"], True)
            mappings[item["label"]] = art["id"]
        for frame in service.store.frames():
            policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
            changed = False
            for event in policy["special_days"]:
                if event["label"] in mappings and not event["artwork_id"]:
                    event["artwork_id"] = mappings[event["label"]]
                    assigned += 1
                    changed = True
            if changed:
                service.store.set_policy(frame["id"], FramePolicy.model_validate(policy))
    return {"artworks_added": added, "events_assigned": assigned, "occasion_count": len(mappings)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "install"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--review-dir", type=Path)
    parser.add_argument("--frame", default="emily-e1002")
    args = parser.parse_args()
    service = Service()
    if args.mode == "stage":
        if not args.review_dir:
            parser.error("stage requires --review-dir")
        stage(service, args.root, args.review_dir, args.frame)
    else:
        print(json.dumps(install(service, args.root)))


if __name__ == "__main__":
    main()
