"""Replay the reviewed selection without downloading whole repositories or asset packs."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("art"))
    parser.add_argument("--lock", type=Path, default=Path("art/related-art.lock.json"))
    args = parser.parse_args()
    target = args.output.resolve()
    lock = json.loads(args.lock.read_text())
    catalog_path = target / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    known = {a["id"]: a for a in catalog["artworks"]}
    for artwork in lock["artworks"]:
        if artwork["id"] in known and known[artwork["id"]] != artwork:
            raise ValueError("Existing curation differs from the reviewed lock")
    for item in lock["downloads"]:
        path = (target / item["asset"]).resolve()
        if not path.is_relative_to(target):
            raise ValueError("Download path escapes the art directory")
        if not item["url"].startswith("https://"):
            raise ValueError("Artwork downloads require HTTPS")
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
            continue
        request = urllib.request.Request(item["url"], headers={"User-Agent": "Emviary/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(8_000_001)
        if len(data) > 8_000_000 or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"Source hash or size differs: {item['asset']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    for name, notice in lock["local_notices"].items():
        path = (target / name).resolve()
        if not path.is_relative_to(target):
            raise ValueError("Notice path escapes the art directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(notice)
    for artwork in lock["artworks"]:
        path = target / artwork["asset"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != artwork["asset_sha256"]:
            raise ValueError("Master differs from reviewed artwork")
        with Image.open(path) as image:
            if artwork["kind"] == "cutout" and image.mode != "RGBA":
                raise ValueError("Cutouts require alpha transparency")
            image.verify()
        known[artwork["id"]] = artwork
    catalog.update(
        license="mixed",
        artworks=list(known.values()),
        source_collections=lock["source_collections"],
        **lock["catalog_metadata"],
    )
    catalog.pop("license_url", None)
    temporary = catalog_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(catalog, indent=2) + "\n")
    temporary.replace(catalog_path)
    print(f"Catalog now contains {len(known)} attributed images")


if __name__ == "__main__":
    main()
