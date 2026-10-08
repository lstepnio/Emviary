import json

import pytest
from fastapi.testclient import TestClient

from emviary import render
from emviary.api import create_app


def test_reference_plate_can_be_browsed_but_cannot_be_rendered(service, tmp_path):
    reference = next(a for a in service.settings.artworks if a.get("kind") == "field_study")
    with pytest.raises(ValueError, match="seasonally"):
        render.choose_art([reference], "2026-10-08", {}, [], "reference")
    policy = service.settings.config.frame_defaults.model_dump()
    plan = {"local_date": "2026-10-08", "inputs": {}, "policy": policy, "artworks": [reference]}
    with pytest.raises(ValueError, match="Reference"):
        render.compose(service.settings.art_dir, reference, plan, tmp_path / "reference.png")
    with TestClient(create_app(service, schedule=False)) as client:
        assert client.get("/art/" + reference["id"]).headers["content-type"] == "image/png"
        assert "Web reference only" in client.get("/library").text
        assert "MIT License" in client.get("/art-license/" + reference["id"]).text


def test_plates_and_bird_counts_respect_panel_capacity(service):
    plate = next(a for a in service.settings.artworks if a.get("kind") == "plate")
    cutout = next(
        a for a in service.settings.artworks if a["scientific_name"] != plate["scientific_name"]
    )
    policy = service.settings.config.frame_defaults.model_dump()
    for n in range(50):
        selected = render.choose_artworks([plate, cutout], "2026-10-08", {}, [], str(n), policy)
        assert len(selected) == 1
    two_birds = {**plate, "depicted_birds": 2}
    policy["max_birds"] = 1
    assert render.choose_artworks([two_birds, cutout], "2026-10-08", {}, [], "1", policy) == [
        cutout
    ]


def test_sharealike_credits_follow_the_selected_assets(service, frame):
    works = service.settings.artworks
    nc = next(a for a in works if a["license"] == "CC-BY-NC-SA-4.0")
    sa = next(a for a in works if a["license"] == "CC-BY-SA-4.0")
    mit = next(a for a in works if a["license"] == "MIT" and a["approved"])
    assert render.composition_license([nc, mit]) == nc["license"]
    assert render.composition_license([sa, mit]) == sa["license"]
    with pytest.raises(ValueError, match="Incompatible"):
        render.composition_license([nc, sa])
    policy = service.settings.config.frame_defaults.model_dump()
    for n in range(50):
        chosen = render.choose_artworks([nc, sa, mit], "2026-10-08", {}, [], str(n), policy)
        assert render.compatible_licenses(chosen)
    result = service.prepare(frame[0], "2026-10-08")
    manifest = json.loads(result["manifest"])
    assert manifest["license"] == render.composition_license(manifest["artworks"])
    assert manifest["artwork_licenses"] == sorted({a["license"] for a in manifest["artworks"]})


def test_breeding_plumage_and_migrant_art_are_seasonal(service):
    goldfinch = next(
        a for a in service.settings.artworks if a["scientific_name"] == "Spinus tristis"
    )
    hummingbird = next(
        a for a in service.settings.artworks if a["scientific_name"] == "Selasphorus platycercus"
    )
    for item in (goldfinch, hummingbird):
        with pytest.raises(ValueError, match="seasonally"):
            render.choose_art([item], "2026-12-01", {}, [], "winter")
        assert render.choose_art([item], "2026-06-01", {}, [], "summer") == item
    plate = next(a for a in service.settings.artworks if a.get("kind") == "plate")
    with TestClient(create_app(service, schedule=False)) as client:
        assert client.get("/art/" + plate["id"]).headers["content-type"] == "image/jpeg"
