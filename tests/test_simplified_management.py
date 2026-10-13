import json
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from test_owner import sign_in

from emviary.service import Service
from emviary.settings import FramePolicy


def test_single_special_days_panel_upload_assign_and_removal_guard(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage/events?frame=test-frame").text
    assert 'id="special-day-art"' in page and "Artwork collection" in page
    assert 'href="/manage/event-art' not in page
    image = BytesIO()
    Image.new("RGB", (100, 100), "green").save(image, "PNG")
    result = client.post(
        "/manage/event-art/upload",
        data={"csrf": csrf, "frame": frame[0], "title": "Spring meadow"},
        files={"image": ("spring.png", image.getvalue(), "image/png")},
        follow_redirects=False,
    )
    assert result.status_code == 303
    target = urlsplit(result.headers["location"])
    assert target.path == "/manage/events" and target.fragment == "special-day-art"
    assert parse_qs(target.query)["frame"] == [frame[0]]
    art = service.event_art.entries()[0]
    assert art["approved"]
    assert (
        client.post(
            "/manage/frames/test-frame/special-days",
            data={
                "csrf": csrf,
                "date": "2026-03-01",
                "label": "Spring",
                "theme": "celebration",
                "artwork_id": art["id"],
                "annual": "on",
                "enabled": "on",
            },
        ).status_code
        == 200
    )
    page = client.get("/manage/events?frame=test-frame").text
    assert "Assigned to:" in page and "Spring meadow" in page
    assert "Awaiting review" not in page and 'value="approve"' not in page
    assert (
        client.post(
            "/manage/event-art/" + art["id"], data={"csrf": csrf, "action": "remove"}
        ).status_code
        == 400
    )
    policy = json.loads(service.store.frame(frame[0])["policy"])
    assert policy["special_days"][0]["artwork_id"] == art["id"]
    assert art["id"] not in {a["id"] for a in service.settings.artworks}


def test_retired_controls_and_routes_preserve_frame_navigation(
    service, frame, tmp_path, monkeypatch
):
    first = service.prepare(frame[0], offline=True)
    service.store.telemetry(frame[0], None, "test", "", first["body_hash"])
    next_image = service.prepare(frame[0], force=True, offline=True)
    before = service.store.frame(frame[0])["policy"]
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    for path in ("/manage", "/manage/appearance", "/manage/artwork", "/manage/events"):
        page = client.get(path).text
        for removed in ("Birds to include", "Panel review", "Frame history", "species_controls"):
            assert removed not in page
    result = client.get("/manage/images?frame=test-frame&offset=24", follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"] == "/manage?frame=test-frame"
    for path in (
        "/manage/artwork/" + first["artwork_id"] + "/review",
        "/manage/images/" + str(first["id"]) + "/remove",
        "/manage/images/" + str(first["id"]) + "/restore",
    ):
        assert client.post(path, data={"csrf": csrf}).status_code == 404
    next_available = service.store.navigation_image(
        service.store.frame(frame[0]), "next", first["body_hash"]
    )
    assert next_available["id"] == next_image["id"]
    assert service.store.frame(frame[0])["policy"] == before
    assert client.get("/manage/images/" + str(next_image["id"]) + "/preview").status_code == 200


def test_legacy_event_art_becomes_ready_once_without_changing_originals(service, frame):
    image = BytesIO()
    Image.new("RGB", (100, 100), "blue").save(image, "PNG")
    art = service.event_art.upload(image.getvalue(), "Winter", "Fixture")
    legacy = {**art, "approved": False}
    service.event_art.save([legacy])
    original = service.event_art.path(art).read_bytes()
    policy = FramePolicy(allowed_species=["Poecile atricapillus"])
    service.store.set_policy(frame[0], policy)
    migrated = Service(service.settings, providers=service.providers, converter=service.converter)
    assert migrated.event_art.entries() == [art]
    assert migrated.event_art.path(art).read_bytes() == original
    assert json.loads(migrated.store.frame(frame[0])["policy"]) == policy.model_dump()
    manifest = migrated.event_art.manifest.read_bytes()
    timestamp = migrated.event_art.manifest.stat().st_mtime_ns
    Service(service.settings, providers=service.providers, converter=service.converter)
    assert migrated.event_art.manifest.read_bytes() == manifest
    assert migrated.event_art.manifest.stat().st_mtime_ns == timestamp
