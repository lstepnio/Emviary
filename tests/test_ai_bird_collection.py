"""Guard the original collection's species coverage, provenance and display assets."""

import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "art"
MANIFEST = ART / "provenance/ai-color-cutouts/manifest.json"


def test_every_catalogue_species_has_one_original_active_variant():
    collection = json.loads(MANIFEST.read_text())
    catalog = json.loads((ART / "catalog.json").read_text())["artworks"]
    originals = collection["artworks"]
    species = [a["scientific_name"] for a in originals]
    assert len(species) == len(set(species)) == 63
    assert set(species) == {a["scientific_name"] for a in catalog}
    active = {a["id"]: a for a in catalog}
    for a in originals:
        assert active[a["id"]]["approved"]
        assert active[a["id"]]["asset_sha256"] == a["asset_sha256"]
        assert a["reference_images"] == []
        assert hashlib.sha256(a["prompt"].encode()).hexdigest() == a["prompt_sha256"]
    assert collection["input_image_count"] == 0
    reviews = collection["review"]["packed_outputs"]
    assert len(reviews) == 84
    for prefix in ("solo-", "trio-"):
        assert {i for r in reviews if r["name"].startswith(prefix) for i in r["artwork_ids"]} == {
            a["id"] for a in originals
        }


def test_original_masters_are_unique_transparent_and_uncropped():
    artworks = json.loads(MANIFEST.read_text())["artworks"]
    assert len({a["asset_sha256"] for a in artworks}) == len(artworks)
    for a in artworks:
        path = ART / a["asset"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == a["asset_sha256"]
        with Image.open(path) as image:
            assert image.mode == "RGBA"
            alpha = image.getchannel("A")
            low, high = alpha.getextrema()
            assert low == 0 and high >= 250
            box = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
            assert box and min(box[0], box[1], image.width - box[2], image.height - box[3]) >= 5
        assert (ART / a["license_file"]).is_file()
