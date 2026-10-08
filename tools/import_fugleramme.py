"""Import a pinned, attributed Denver subset without modifying the originals."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image

REVISION = "62202503ddd059875367046d472d564840cd9cc6"
SPECIES = [
    (
        "Poecile atricapillus",
        "Black-capped Chickadee",
        ["poecile-atricapillus", "poecile-atricapillus-2"],
    ),
    ("Cyanocitta cristata", "Blue Jay", ["cyanocitta-cristata"]),
    ("Corvus brachyrhynchos", "American Crow", ["corvus-brachyrhynchos"]),
    ("Haemorhous mexicanus", "House Finch", ["haemorhous-mexicanus-2", "haemorhous-mexicanus-3"]),
    ("Pica hudsonia", "Black-billed Magpie", ["pica-hudsonia", "pica-hudsonia-2"]),
    ("Turdus migratorius", "American Robin", ["turdus-migratorius"]),
    ("Sitta canadensis", "Red-breasted Nuthatch", ["sitta-canadensis"]),
    ("Dryobates pubescens", "Downy Woodpecker", ["dryobates-pubescens"]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--output", type=Path, default=Path("art"))
    args = parser.parse_args()
    revision = subprocess.check_output(
        ["git", "-C", str(args.checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise ValueError("Checkout differs from the reviewed artwork revision")
    source = args.checkout / "assets/artwork/classic"
    manifest = json.loads((source / "manifest.json").read_text())
    target = args.output
    (target / "masters").mkdir(parents=True, exist_ok=True)
    (target / "fonts").mkdir(exist_ok=True)
    works = []
    for scientific, common, variants in SPECIES:
        for variant in variants:
            original = source / f"birds/{variant}.webp"
            attribution = manifest[f"birds/{variant}.webp"]
            with Image.open(original) as image:
                if image.mode != "RGBA":
                    raise ValueError(f"Cutout has no alpha: {original.name}")
                image.verify()
            asset = f"masters/{variant}.webp"
            shutil.copy2(original, target / asset)
            works.append(
                {
                    "id": variant,
                    "scientific_name": scientific,
                    "common_name": common,
                    "months": list(range(1, 13)),
                    "asset": asset,
                    "approved": True,
                    "review_status": "Upstream curated; physical panel review pending",
                    "asset_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                    "source": attribution["source"],
                    "source_url": attribution["url"],
                    "upstream_asset": f"assets/artwork/classic/birds/{variant}.webp",
                    "license": "CC-BY-SA-4.0",
                    "credit": (
                        "Original plate source linked; "
                        "cutout/restoration by Fugleramme contributors"
                    ),
                }
            )
    shutil.copy2(source / "ATTRIBUTION.md", target / "FUGLERAMME-ATTRIBUTION.md")
    fonts = args.checkout / "assets/fonts/ebgaramond"
    for name in ("EBGaramond-Italic.ttf", "OFL.txt"):
        shutil.copy2(fonts / name, target / "fonts" / name)
    shutil.copy2(args.checkout / "LICENSE", target / "FUGLERAMME-CODE-LICENSE.txt")
    catalog = {
        "license": "CC-BY-SA-4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "upstream": "https://github.com/arnegiacomo/fugleramme",
        "upstream_revision": REVISION,
        "curation": "Denver starter subset of Fugleramme classic artwork",
        "adaptations": (
            "Original cutouts unchanged; outputs resize, compose, label, and dither them"
        ),
        "artworks": works,
    }
    (target / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"Imported {len(works)} cutouts covering {len(SPECIES)} species")


if __name__ == "__main__":
    main()
