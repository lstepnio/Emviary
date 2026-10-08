import io
import json

import pytest
from PIL import Image
from test_owner import sign_in

from emviary import render
from emviary.event_art import EventArt, event_presets, import_presets
from emviary.settings import FramePolicy, SpecialDay


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (800, 480), "#d4a46a").save(output, "PNG")
    return output.getvalue()


def test_bulk_import_preserves_customization_and_year_specific_dates():
    holidays = import_presets([], "holidays", 2026)
    assert len(holidays) == 17
    thanksgiving = next(d for d in holidays if d["label"] == "Thanksgiving")
    assert thanksgiving["date"] == "2026-11-26" and not thanksgiving["annual"]
    holidays[0]["enabled"] = False
    holidays[0]["message"] = "Our own greeting"
    assert import_presets(holidays, "holidays", 2026) == holidays
    seasons = import_presets(holidays, "seasons", 2026)
    assert len(seasons) == 21
    assert all(d["annual"] for d in seasons if d["id"].startswith("preset-first-day"))
    assert next(d for d in seasons if "fall (meteorological)" in d["label"])["date"] == "2026-09-01"
    assert len(import_presets(seasons, "seasons", 2026)) == 21
    assert len(event_presets("holidays", 2027)) == 17
    FramePolicy(special_days=seasons)
    with pytest.raises(ValueError):
        event_presets("seasons", 2101)


def test_event_art_validation_and_persistence(tmp_path):
    library = EventArt(tmp_path)
    with pytest.raises(ValueError):
        library.upload(b"not an image", "Fall", "Owner")
    transparent = io.BytesIO()
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(transparent, "PNG")
    with pytest.raises(ValueError):
        library.upload(transparent.getvalue(), "Fall", "Owner")
    entry = library.upload(image_bytes(), "Fall", "Owner")
    assert not entry["approved"] and entry["event_only"]
    assert EventArt(tmp_path).entries() == [entry]
    with pytest.raises(ValueError):
        library.path({"asset": "../escape.png"})
    library.review(entry["id"], True)
    assert library.entries()[0]["approved"]
    library.remove(entry["id"])
    assert not library.entries() and not library.path(entry).exists()


def test_nonbird_event_override_and_ordinary_rotation_isolation(service, frame, tmp_path):
    entry = service.event_art.upload(image_bytes(), "Fall landscape", "Owner")
    service.event_art.review(entry["id"], True)
    policy = service.settings.config.frame_defaults.model_dump()
    policy["special_days"] = [
        SpecialDay(
            id="fall", date="2026-09-22", label="Hello, fall!", annual=False, artwork_id=entry["id"]
        ).model_dump()
    ]
    service.store.set_policy(frame[0], FramePolicy.model_validate(policy))
    result = service.prepare(frame[0], "2026-09-22", offline=True)
    manifest = json.loads(result["manifest"])
    assert manifest["artworks"][0]["id"] == entry["id"]
    assert manifest["layout"]["bird_count"] == 0
    assert service.store.bird_counts() == {}
    assert manifest["license"] == "Owner-Provided"
    assert service.preview_special_day(frame[0], "fall")[:2] == b"\xff\xd8"
    ordinary = json.loads(service.prepare(frame[0], "2026-09-23", offline=True)["manifest"])
    assert all(not a.get("event_only") for a in ordinary["artworks"])
    assert all(a["id"] != entry["id"] for a in service.settings.artworks)
    with pytest.raises(ValueError, match="requires a selected special day"):
        render.compose(
            service.settings.art_dir,
            manifest["artwork"],
            {**manifest, "special_day": None},
            tmp_path / "bad.png",
            service.event_art.root,
        )
    policy["special_days"][0]["enabled"] = False
    service.store.set_policy(frame[0], FramePolicy.model_validate(policy))
    disabled = json.loads(service.prepare(frame[0], "2026-09-22", offline=True)["manifest"])
    assert disabled["special_day"] is None
    assert all(not a.get("event_only") for a in disabled["artworks"])


def test_owner_upload_review_select_remove_and_bulk_csrf(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    url = "/manage/event-art/upload"
    data = {"csrf": csrf, "title": "Autumn", "attribution": "My own photo"}
    files = {"image": ("../../bad.png", image_bytes(), "image/png")}
    assert client.post(url, data={**data, "csrf": "bad"}, files=files).status_code == 403
    assert (
        client.post(
            url, data=data, files=files, headers={"Origin": "https://wrong.example"}
        ).status_code
        == 403
    )
    assert client.post(url, data=data, files=files, follow_redirects=False).status_code == 303
    art = service.event_art.entries()[0]
    assert not art["approved"]
    assert client.get(f"/manage/event-art/{art['id']}/image").status_code == 200
    event = {
        "csrf": csrf,
        "date": "2026-09-22",
        "label": "Fall",
        "theme": "celebration",
        "enabled": "on",
        "artwork_id": art["id"],
    }
    event_url = "/manage/frames/test-frame/special-days"
    assert client.post(event_url, data=event).status_code == 400
    review_url = f"/manage/event-art/{art['id']}"
    assert (
        client.post(
            review_url, data={"csrf": csrf, "action": "approve"}, follow_redirects=False
        ).status_code
        == 303
    )
    assert client.post(event_url, data=event, follow_redirects=False).status_code == 303
    assert client.post(review_url, data={"csrf": csrf, "action": "remove"}).status_code == 400
    stored = json.loads(service.store.frame(frame[0])["policy"])["special_days"]
    event["id"] = stored[0]["id"]
    event["artwork_id"] = ""
    assert client.post(event_url, data=event, follow_redirects=False).status_code == 303
    assert (
        client.post(
            review_url, data={"csrf": csrf, "action": "remove"}, follow_redirects=False
        ).status_code
        == 303
    )
    importer = event_url + "/import"
    assert (
        client.post(importer, data={"csrf": "bad", "group": "holidays", "year": 2026}).status_code
        == 403
    )
    for _ in range(2):
        assert (
            client.post(
                importer,
                data={"csrf": csrf, "group": "holidays", "year": 2026},
                follow_redirects=False,
            ).status_code
            == 303
        )
    assert len(json.loads(service.store.frame(frame[0])["policy"])["special_days"]) == 18


def test_event_art_backup_and_cache_invalidation(service, frame, tmp_path):
    before = service.prepare(frame[0], "2026-09-22", offline=True)
    entry = service.event_art.upload(image_bytes(), "Fall", "Owner")
    after = service.prepare(frame[0], "2026-09-22", offline=True)
    assert after["profile_hash"] != before["profile_hash"]
    backup = tmp_path / "recovery"
    service.backup(backup)
    assert json.loads((backup / "event-art/manifest.json").read_text())[0]["id"] == entry["id"]
    assert (backup / "event-art" / entry["asset"]).is_file()
