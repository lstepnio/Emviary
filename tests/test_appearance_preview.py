"""Appearance journey uses isolated data and the real compositor."""

import json
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.service import Service
from emviary.settings import FramePolicy


def test_draft_does_not_save_or_advance_and_queue_uses_exact_bytes(service, frame):
    identifier, bearer = frame
    original = service.store.frame(identifier)
    policy = FramePolicy.model_validate_json(original["policy"])
    policy.show_species_name = False
    before_counts = service.store.bird_counts()
    token = service.preview_appearance(identifier, policy)
    draft = service.appearance_preview(identifier, token)
    assert service.store.frame(identifier) == original
    assert service.store.bird_counts() == before_counts
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    queued = service.queue_appearance_preview(identifier, token, policy)
    assert service.cache_path(queued["path"]).read_bytes() == draft["packed"]
    assert service.cache_path(queued["preview_path"]).read_bytes() == draft["preview"]
    saved = service.store.frame(identifier)
    assert json.loads(saved["policy"])["show_species_name"] is False
    assert saved["last_served_etag"] == original["last_served_etag"]
    assert json.loads(queued["manifest"])["appearance_preview"] is True
    with pytest.raises(ValueError):
        service.queue_appearance_preview(identifier, token, policy)
    restarted = Service(
        service.settings,
        providers=service.providers,
        converter=service.converter,
        clock=service.clock,
    )
    assert json.loads(restarted.store.frame(identifier)["policy"])["show_species_name"] is False
    assert restarted.store.slot_image(identifier, "navigation")["id"] == queued["id"]
    client = TestClient(create_app(restarted, schedule=False))
    response = client.get("/v1/image", headers={"Authorization": "Bearer " + bearer})
    assert response.status_code == 200 and response.content == draft["packed"]


def test_changed_expired_failed_and_wrong_frame_previews_preserve_saved_state(service, frame):
    identifier = frame[0]
    policy = FramePolicy.model_validate_json(service.store.frame(identifier)["policy"])
    token = service.preview_appearance(identifier, policy)
    changed = policy.model_copy(update={"show_species_name": not policy.show_species_name})
    with pytest.raises(ValueError, match="Settings changed"):
        service.queue_appearance_preview(identifier, token, changed)
    with pytest.raises(ValueError, match="expired"):
        service.appearance_preview("other-frame", token)
    service.store.set_policy(identifier, changed)
    saved = service.store.frame(identifier)
    with pytest.raises(ValueError, match="Saved settings changed"):
        service.queue_appearance_preview(identifier, token, policy)
    assert service.store.frame(identifier) == saved
    token = service.preview_appearance(identifier, changed)
    service._appearance_previews[token]["expires"] = service.clock() - timedelta(seconds=1)
    with pytest.raises(ValueError, match="expired"):
        service.queue_appearance_preview(identifier, token, changed)

    def broken(*args):
        raise TimeoutError("isolated converter failure")

    service.converter = broken
    with pytest.raises(TimeoutError):
        service.preview_appearance(identifier, changed)
    assert service.store.frame(identifier) == saved
    assert service.store.active_image(saved) is None


def test_owner_preview_queue_auth_validation_and_persistence(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    base = "/manage/frames/test-frame/"
    form = {"csrf": csrf, "wake": "04:10", "max_birds": "1", "preset": "soft", "dither": "stucki"}
    original = service.store.frame(frame[0])
    response = client.post(base + "appearance-preview", data=form)
    assert response.status_code == 200
    result = response.json()
    preview = client.get(result["preview_url"])
    assert preview.status_code == 200 and preview.headers["cache-control"] == "no-store"
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.get(result["preview_url"]).status_code == 401
    assert service.store.frame(frame[0]) == original
    invalid = client.post(base + "appearance-preview", data={**form, "max_birds": "42"})
    assert invalid.status_code == 400 and "message" in invalid.json()
    queued = client.post(
        base + "settings",
        data={**form, "action": "queue", "preview_token": result["token"]},
        follow_redirects=False,
    )
    assert queued.status_code == 303 and "queued=1" in queued.headers["location"]
    assert (
        service.cache_path(
            service.store.active_image(service.store.frame(frame[0]))["preview_path"]
        ).read_bytes()
        == preview.content
    )
    page = client.get(queued.headers["location"])
    assert "Delivery and physical-panel refresh are not yet confirmed" in page.text
    assert "data-appearance-preview" in page.text


def test_reviewed_image_wins_over_existing_daily_slot_without_consuming_preview(service, frame):
    identifier = frame[0]
    service.prepare(identifier, "2026-10-08")
    policy = FramePolicy.model_validate_json(service.store.frame(identifier)["policy"])
    token = service.preview_appearance(identifier, policy)
    with service.store.connect() as db:
        daily = service.store.active_image(service.store.frame(identifier))["id"]
        db.execute(
            "INSERT INTO prepared_slots(frame_id,purpose,image_id,cycle) "
            "VALUES(?,'scheduled',?,'fixture')",
            (identifier, daily),
        )
    queued = service.queue_appearance_preview(identifier, token, policy)
    selected, retain = service.select_image(service.store.frame(identifier), "latest", "")
    assert selected["id"] == queued["id"] and retain is False


def test_native_html_preview_has_working_authenticated_queue_form(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    fields = {
        "csrf": csrf,
        "wake": "04:15",
        "max_birds": "2",
        "preset": "balanced",
        "dither": "stucki",
    }
    response = client.post(
        "/manage/frames/test-frame/appearance-preview", data=fields, headers={"Accept": "text/html"}
    )
    assert response.status_code == 200
    assert "Unsaved preview" in response.text and "Save and queue preview" in response.text
    token = re.search(r'name="preview_token" value="([^"]+)"', response.text).group(1)
    preview = service.appearance_preview(frame[0], token)
    response = client.post(
        "/manage/frames/test-frame/settings",
        data={**fields, "action": "queue", "preview_token": token},
    )
    assert response.status_code == 200
    queued = service.store.slot_image(frame[0], "navigation")
    assert service.cache_path(queued["path"]).read_bytes() == preview["packed"]
