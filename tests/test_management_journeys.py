"""Cross-page journeys with populated, empty, missing and failing dependencies."""

import json
from html.parser import HTMLParser
from io import BytesIO

import pytest
from PIL import Image
from test_owner import sign_in

from emviary.settings import SpecialDay

PAGES = ("", "/appearance", "/events", "/artwork", "/battery", "/settings", "/recovery")


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.assets, self.links, self.forms = [], [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag in ("img", "script") and attrs.get("src", "").startswith("/"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs["href"])
        if tag == "a" and attrs.get("href", "").startswith("/manage"):
            self.links.append(attrs["href"])
        if tag == "form":
            self.forms.append(attrs)


def populate(service, frame):
    first = service.prepare(frame[0], offline=True)
    service.store.telemetry(frame[0], 77, "v0.8.10", "", first["body_hash"])
    service.prepare(frame[0], force=True, offline=True)
    service.prepare_due()
    policy = service.settings.config.frame_defaults.model_copy(deep=True)
    policy.special_days = [
        SpecialDay(
            id="birthday",
            date="2026-10-21",
            label="Birthday",
            message="Have a beautiful day",
            annual=True,
        )
    ]
    service.store.add_frame("second-frame", policy)
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO device_samples(frame_id,recorded_at,metrics) VALUES(?,?,?)",
            (
                frame[0],
                service.clock().isoformat(),
                json.dumps(
                    {
                        "previous_result": "failed",
                        "previous_http_status": 503,
                        "ssid": "Home & garden",
                        "offline_mode": True,
                        "wifi_networks": [{"ssid": "Home & garden", "password_set": True}],
                        "offline_cache_count": 3,
                        "offline_rotations": 2,
                        "rssi_dbm": -72,
                        "firmware_update_result": "retry_held",
                    }
                ),
            ),
        )
    return first


@pytest.mark.parametrize("populated", [False, True])
def test_every_management_page_links_assets_and_unique_ids(
    service, frame, tmp_path, monkeypatch, populated
):
    if populated:
        populate(service, frame)
    client, _ = sign_in(service, tmp_path, monkeypatch)
    visited = set()
    for path in PAGES:
        response = client.get("/manage" + path + "?frame=" + frame[0])
        assert response.status_code == 200, path
        doc = Document(response.text)
        assert len(doc.ids) == len(set(doc.ids)), (path, doc.ids)
        for asset in doc.assets:
            if asset not in visited:
                result = client.get(asset)
                assert result.status_code == 200, (path, asset, result.status_code)
                visited.add(asset)
        for link in doc.links:
            if link not in visited:
                result = client.get(link)
                assert result.status_code == 200, (path, link, result.status_code)
                visited.add(link)
        assert all(f.get("method", "get").lower() in {"post", "get"} for f in doc.forms)
    if populated:
        for path in PAGES:
            assert client.get("/manage" + path + "?frame=second-frame").status_code == 200


@pytest.mark.parametrize("path", PAGES)
def test_pages_before_enrollment(service, tmp_path, monkeypatch, path):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    response = client.get("/manage" + path)
    assert response.status_code == 200
    assert response.text.count("<details") == response.text.count("</details>")


@pytest.mark.parametrize(
    "suffix", ["display", "preview", "prepared/scheduled", "prepared/navigation", "provision"]
)
def test_deleted_frame_links_are_controlled_404(service, frame, tmp_path, monkeypatch, suffix):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    assert client.get("/manage/frames/deleted/" + suffix).status_code == 404
    assert client.get("/manage/artwork?frame=deleted").status_code == 404
    assert client.get("/manage/event-art?frame=deleted").status_code == 404


def test_missing_preview_reports_recoverable_error(service, frame, tmp_path, monkeypatch):
    image = service.prepare(frame[0], offline=True)
    service.store.telemetry(frame[0], 77, "v0.8.10", "", image["body_hash"])
    client, _ = sign_in(service, tmp_path, monkeypatch)
    service.cache_path(image["preview_path"]).unlink()
    for suffix in ("display", "preview", "prepared/navigation"):
        response = client.get("/manage/frames/" + frame[0] + "/" + suffix)
        assert response.status_code == 503
        assert "Try preparing it again" in response.text
    assert client.get("/manage/recovery").status_code == 200


def test_settings_event_art_and_validation_journey(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    url = "/manage/frames/" + frame[0]
    before = service.store.frame(frame[0])["policy"]
    assert client.post(url + "/settings", data={"csrf": csrf, "wake": "25:00"}).status_code == 400
    assert service.store.frame(frame[0])["policy"] == before
    response = client.post(
        url + "/settings",
        data={
            "csrf": csrf,
            "wake": "05:20",
            "max_birds": "2",
            "preset": "soft",
            "dither": "stucki",
            "labels": "on",
            "weather": "on",
            "forecast_temperatures": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert json.loads(service.store.frame(frame[0])["policy"])["wake_local_time"] == "05:20"
    invalid = client.post(url + "/wifi", data={"csrf": csrf, "ssid": "", "password": ""})
    assert invalid.status_code == 400
    assert client.get("/manage/settings").status_code == 200
    image = BytesIO()
    Image.new("RGB", (100, 100), "blue").save(image, "PNG")
    uploaded = client.post(
        "/manage/event-art/upload",
        data={"csrf": csrf, "frame": frame[0], "title": "Birthday meadow"},
        files={"image": ("meadow.png", image.getvalue(), "image/png")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303
    art = service.event_art.entries()[0]
    event = client.post(
        url + "/special-days",
        data={
            "csrf": csrf,
            "date": "2026-10-09",
            "label": "Birthday",
            "theme": "celebration",
            "artwork_id": art["id"],
            "enabled": "on",
            "annual": "on",
        },
    )
    assert event.status_code == 200
    assert "Birthday meadow" in client.get("/manage/events").text
    assert client.get("/manage/recovery").status_code == 200


def test_all_pages_survive_malformed_optional_evidence(service, frame, tmp_path, monkeypatch):
    populate(service, frame)
    client, _ = sign_in(service, tmp_path, monkeypatch)
    with service.store.connect() as db:
        db.execute("UPDATE device_samples SET metrics='[]',recorded_at='invalid'")
        db.execute("UPDATE prepared_slots SET last_attempt_at='invalid',error='ValueError'")
        db.execute("UPDATE battery_samples SET recorded_at='invalid'")
    backup = service.settings.backup_dir / "corrupt"
    backup.mkdir()
    (backup / "COMPLETE").write_text("[]")
    for path in PAGES:
        assert client.get("/manage" + path).status_code == 200, path


@pytest.mark.parametrize("contact", ["invalid", "2026-10-08T01:00:00", "2999-01-01T00:00:00Z"])
def test_invalid_contact_cannot_break_any_management_page(
    service, frame, tmp_path, monkeypatch, contact
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    with service.store.connect() as db:
        db.execute("UPDATE frames SET last_contact=?", (contact,))
    for path in PAGES:
        assert client.get("/manage" + path).status_code == 200, path


def test_missing_recovery_credential_has_guided_remedy_instead_of_broken_downloads(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    response = client.get("/manage/recovery")
    assert "saved device credential is missing" in response.text
    assert "/provision?import_file=true" not in response.text
    assert client.get("/manage/frames/" + frame[0] + "/provision").status_code == 409


def test_weather_provenance_page_uses_validated_cached_sources(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    now = service.clock()
    for source in ("open_meteo", "nws"):
        service.store.save_snapshot(
            frame_id := service.store.frame(frame[0])["site_id"],
            "weather_" + source,
            "2026-10-08",
            {"fetched_at": now.isoformat()},
        )
    service.store.save_snapshot(frame_id, "open_meteo", "2026-10-08", {"agreement": "disagreement"})
    result = client.get("/manage/settings")
    assert result.status_code == 200
    assert "Sources differ" in result.text and "Last received" in result.text


def test_every_management_mutation_rejects_bad_csrf_before_changing_state(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    visited = []
    substitutions = {
        "identifier": frame[0],
        "frame_id": frame[0],
        "artwork_id": "missing",
        "image_id": "1",
        "day_id": "missing",
        "session_id": "missing",
    }
    before = service.store.frame(frame[0])
    for route in client.app.routes:
        if (
            not route.path.startswith("/manage")
            or "POST" not in route.methods
            or route.path == "/manage/login"
        ):
            continue
        path = route.path.format_map(substitutions)
        options = (
            {"files": {"image": ("fixture.png", b"fixture", "image/png")}}
            if path.endswith("/upload")
            else {}
        )
        result = client.post(path, data={"csrf": "invalid"}, follow_redirects=False, **options)
        assert result.status_code == 403, (path, result.status_code)
        visited.append(path)
    assert len(visited) >= 30
    assert service.store.frame(frame[0]) == before
