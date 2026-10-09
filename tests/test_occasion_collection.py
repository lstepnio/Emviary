import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from emviary.settings import FramePolicy

spec = importlib.util.spec_from_file_location(
    "install_occasion_art", Path(__file__).resolve().parents[1] / "tools/install_occasion_art.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def make_collection(root, reviewed=True):
    root.mkdir()
    image = io.BytesIO()
    Image.new("RGB", (80, 48), "red").save(image, "PNG")
    raw = image.getvalue()
    (root / "holiday.png").write_bytes(raw)
    manifest = {
        "source": "AI-generated test fixture",
        "source_url": "https://example.com/art",
        "generation_method": "Test fixture",
        "artworks": [
            {
                "slug": "holiday",
                "label": "Holiday",
                "asset": "holiday.png",
                "asset_sha256": hashlib.sha256(raw).hexdigest(),
                "reviewed": reviewed,
            }
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_install_preserves_event_settings_custom_art_and_rotation(service, frame, tmp_path):
    root = tmp_path / "collection"
    make_collection(root)
    policy = FramePolicy(
        special_days=[
            dict(id="first", date="2026-01-01", label="Holiday", enabled=False, message="Hello"),
            dict(id="second", date="2027-01-01", label="Holiday", enabled=True, annual=False),
            dict(id="custom", date="2026-02-01", label="Holiday", artwork_id="custom-art"),
        ]
    )
    service.store.set_policy(frame[0], policy)
    before = policy.model_dump()
    birds = service.settings.artworks.copy()
    assert installer.install(service, root) == {
        "artworks_added": 1,
        "events_assigned": 2,
        "occasion_count": 1,
    }
    after = FramePolicy.model_validate_json(service.store.frame(frame[0])["policy"]).model_dump()
    art = service.event_art.entries()[0]
    assert art["approved"] and art["event_only"] and art["depicted_birds"] == 0
    assert art["source_url"] == "https://example.com/art"
    for old, new in zip(before["special_days"], after["special_days"], strict=True):
        assert {k: v for k, v in old.items() if k != "artwork_id"} == {
            k: v for k, v in new.items() if k != "artwork_id"
        }
    assert after["special_days"][2]["artwork_id"] == "custom-art"
    assert service.settings.artworks == birds
    assert installer.install(service, root)["artworks_added"] == 0
    assert installer.install(service, root)["events_assigned"] == 0
    assert len(service.event_art.entries()) == 1


def test_install_requires_review_and_unchanged_originals(service, tmp_path):
    root = tmp_path / "collection"
    make_collection(root, reviewed=False)
    with pytest.raises(ValueError, match="Review"):
        installer.install(service, root)
    (root / "holiday.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest changed"):
        installer.install(service, root)
    assert service.event_art.entries() == []


def test_collection_rejects_paths_outside_collection(tmp_path):
    root = tmp_path / "collection"
    manifest = make_collection(root)
    manifest["artworks"][0]["asset"] = "../holiday.png"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid collection asset"):
        installer.collection(root)
