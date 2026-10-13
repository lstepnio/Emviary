"""Context and recovery checks use isolated owner sessions and fixture storage."""

import json
import re
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from PIL import Image
from test_owner import sign_in

from emviary.api import create_app
from emviary.settings import FramePolicy, SpecialDay


def test_event_art_keeps_frame_context_and_explains_dependencies(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    image = BytesIO()
    Image.new("RGB", (100, 100), "blue").save(image, "PNG")
    response = client.post(
        "/manage/event-art/upload",
        data={"csrf": csrf, "title": "Winter sky", "attribution": "Fixture", "frame": frame[0]},
        files={"image": ("sky.png", image.getvalue(), "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query == {"result": ["uploaded"], "frame": [frame[0]], "focus": ["special-day-art"]}
    assert urlsplit(response.headers["location"]).path == "/manage/events"
    artwork = service.event_art.entries()[0]
    original = service.event_art.path(artwork).read_bytes()
    thumbnail = client.get("/manage/event-art/" + artwork["id"] + "/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["cache-control"] == "private, no-cache"
    assert (
        client.get(
            "/manage/event-art/" + artwork["id"] + "/thumbnail",
            headers={"If-None-Match": thumbnail.headers["etag"]},
        ).status_code
        == 304
    )
    assert service.event_art.path(artwork).read_bytes() == original
    policy = service.settings.config.frame_defaults.model_dump()
    policy["special_days"] = [
        SpecialDay(
            id="winter", date="2026-12-01", label="Winter", artwork_id=artwork["id"]
        ).model_dump()
    ]
    service.store.set_policy(frame[0], FramePolicy.model_validate(policy))
    html = client.get("/manage/event-art?frame=" + frame[0]).text
    assert 'href="/manage/events?frame=test-frame&amp;focus=event-winter#event-winter"' in html
    assert re.search(r'<button[^>]+value="remove"[^>]+disabled', html)
    assert 'value="unapprove"' not in html
    assert (
        client.post(
            "/manage/event-art/" + artwork["id"], data={"csrf": csrf, "action": "remove"}
        ).status_code
        == 400
    )
    assert service.event_art.entries()[0]["approved"]


def test_saved_event_returns_to_its_frame_and_heading(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    response = client.post(
        "/manage/frames/test-frame/special-days",
        data={
            "csrf": csrf,
            "date": "2026-12-01",
            "label": "Winter",
            "theme": "celebration",
            "annual": "on",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    event = json.loads(service.store.frame(frame[0])["policy"])["special_days"][0]
    assert response.headers["location"] == (
        "/manage/events?frame=test-frame&saved=1&focus=event-"
        + event["id"]
        + "#event-"
        + event["id"]
    )
    html = client.get(response.headers["location"]).text
    assert "Winter" in html and "data-event-toggle" in html
    assert re.search(r'<input[^>]*name="enabled"[^>]*data-event-toggle[^>]*checked', html)
    assert "/special-days/" + event["id"] + "/preview" in html
    assert "Test on frame" in html
    response = client.post(
        "/manage/frames/test-frame/special-days",
        data={
            "csrf": csrf,
            "id": event["id"],
            "date": "2026-02-30",
            "label": "Keep my greeting",
            "theme": "celebration",
        },
    )
    assert response.status_code == 400
    assert 'data-error-fields="[&quot;date&quot;]"' in response.text
    assert json.loads(service.store.frame(frame[0])["policy"])["special_days"][0] == event


def test_library_bulk_actions_make_visible_page_scope_explicit(service, tmp_path, monkeypatch):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    html = client.get("/manage/artwork?q=Chickadee").text
    assert 'type="button" class="secondary" data-select-page' in html
    assert 'data-selection-count role="status" aria-live="polite"' in html
    assert re.search(
        r"<details><summary>Manage all artwork outside rotation.*?"
        r'action="/manage/artwork/bulk-delete".*?</details>',
        html,
    )
    assert "including artwork outside these filters and this page" in html


def test_event_changes_reject_stale_form_without_overwriting_saved_calendar(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    original_revision = service.store.frame(frame[0])["config_revision"]
    data = {
        "csrf": csrf,
        "date": "2026-12-01",
        "label": "Winter",
        "theme": "celebration",
        "frame_revision": str(original_revision),
    }
    assert client.post("/manage/frames/test-frame/special-days", data=data).status_code == 200
    saved_policy = service.store.frame(frame[0])["policy"]
    stale = client.post("/manage/frames/test-frame/special-days", data={**data, "label": "Stale"})
    assert stale.status_code == 409
    assert "changed in another tab" in stale.text
    assert service.store.frame(frame[0])["policy"] == saved_policy

    event_id = json.loads(saved_policy)["special_days"][0]["id"]
    stale_remove = client.post(
        "/manage/frames/test-frame/special-days/" + event_id + "/delete",
        data={"csrf": csrf, "frame_revision": str(original_revision)},
    )
    assert stale_remove.status_code == 409
    assert service.store.frame(frame[0])["policy"] == saved_policy


def test_full_artwork_review_is_private_and_available_after_recoverable_removal(
    service, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    artwork = next(a for a in service.settings.artworks if a["approved"])
    url = "/manage/artwork/" + artwork["id"] + "/image"
    original = (service.settings.art_dir / artwork["asset"]).read_bytes()
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.get(url).status_code == 401
    assert client.get(url).content == original
    service.delete_artworks([artwork["id"]])
    assert client.get(url).content == original
    assert anonymous.get(url).status_code == 401


def test_app_hides_artwork_provenance_without_losing_catalog_records(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    before = json.dumps(service.settings.catalog, sort_keys=True)
    for path in ("/library", "/manage/artwork", "/manage/event-art"):
        response = client.get(path)
        for text in (
            "Source artwork",
            "Sources and provenance",
            "Variants and credits",
            "Artwork details and credit",
            "Creator or source",
        ):
            assert text not in response.text
    assert json.dumps(service.settings.catalog, sort_keys=True) == before
