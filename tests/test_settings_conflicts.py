"""Two editors must not silently overwrite each other's saved settings."""

import json
import re

import pytest
from test_owner import sign_in

from emviary.service import Service
from emviary.store import RevisionConflict


def test_rendered_frame_edit_rejects_stale_save_and_survives_restart(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    original = client.get("/manage/appearance?frame=test-frame").text
    revision = re.search(r'name="frame_revision" value="(\d+)"', original).group(1)
    fields = {
        "csrf": csrf,
        "frame_revision": revision,
        "wake": "04:15",
        "max_birds": "2",
        "preset": "balanced",
        "dither": "stucki",
    }
    url = "/manage/frames/test-frame/settings"
    assert client.post(url, data=fields, follow_redirects=False).status_code == 303
    saved = service.store.frame(frame[0])
    conflict = client.post(url, data={**fields, "wake": "06:10"})
    assert conflict.status_code == 409
    assert "another tab" in conflict.text and "Preparation is busy" not in conflict.text
    assert service.store.frame(frame[0]) == saved
    restarted = Service(service.settings, providers=service.providers, converter=service.converter)
    assert json.loads(restarted.store.frame(frame[0])["policy"])["wake_local_time"] == "04:15"


def test_connection_edit_conflict_preserves_newer_configuration(service):
    revision = service.settings_revision()
    first = service.settings.config.model_dump()
    first["sites"][0]["locality_radius_km"] = 12
    service.save_configuration(first, expected_revision=revision)
    stale = service.settings.config.model_dump()
    stale["sites"][0]["locality_radius_km"] = 35
    with pytest.raises(RevisionConflict):
        service.save_configuration(stale, expected_revision=revision)
    assert service.settings.config.sites[0].locality_radius_km == 12


def test_wifi_and_event_forms_carry_revisions_and_navigation_keeps_frame(
    service, frame, tmp_path, monkeypatch
):
    second = "second-frame"
    service.store.add_frame(second, service.settings.config.frame_defaults)
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    for path in ("appearance", "settings", "events", "recovery", "images", "event-art", "battery"):
        response = client.get("/manage/" + path + "?frame=" + second)
        assert response.status_code == 200
        assert 'href="/manage/appearance?frame=second-frame"' in response.text
        assert "Selected frame <strong>second-frame</strong>" in response.text
    page = client.get("/manage/settings?frame=" + second).text
    revision = re.search(r'name="frame_revision" value="(\d+)"', page).group(1)
    data = {
        "csrf": csrf,
        "frame_revision": revision,
        "action": "save",
        "ssid": "Fixture Wi-Fi",
        "open": "on",
    }
    url = "/manage/frames/second-frame/wifi"
    assert client.post(url, data=data, follow_redirects=False).status_code == 303
    saved = service.store.frame(second)
    assert client.post(url, data={**data, "ssid": "Another fixture"}).status_code == 409
    assert service.store.frame(second) == saved
