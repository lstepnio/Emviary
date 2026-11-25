import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.backup_validation import file_digest, verify_backup, write_manifest
from emviary.diagnostics import parse_metrics
from emviary.gift_mode import welcome_image
from emviary.store import RevisionConflict


def draft(service, frame):
    first = service.prepare(frame[0], offline=True)
    return service.gifts.prepare(
        frame[0],
        {
            "heading": "For my love, Emily.",
            "message": "A little nature, every day.",
            "signature": "Love, Luke",
            "first_image_id": first["id"],
        },
    )


def capable(service, frame):
    service.store.device_sample(frame[0], {"gift_version": 1, "gift_state": "idle"}, "v0.8.12")


def test_gift_preview_is_isolated_immutable_weather_free_and_survives_restart(service, frame):
    original = service.store.frame(frame[0])["policy"]
    packet = draft(service, frame)
    assert packet["status"] == "draft"
    assert service.gifts.payload(frame[0])["state"] == "none"
    assert service.store.frame(frame[0])["policy"] == original
    root = service.gifts.root / packet["id"]
    plan = json.loads((root / "first-plan.json").read_text())
    assert plan["inputs"] == {} and not plan["policy"]["show_weather_icon"]
    before = service.gifts.path(packet, "first").read_bytes()
    service.prepare(frame[0], force=True, offline=True)
    assert service.gifts.path(packet, "first").read_bytes() == before
    from emviary.gift_mode import GiftMode

    restored = GiftMode(service)
    assert restored.current(frame[0])["id"] == packet["id"]
    restored.verify_all()


def test_gift_requires_capability_exact_reviewed_draft_and_valid_both_assets(service, frame):
    packet = draft(service, frame)
    with pytest.raises(ValueError, match="gift-capable"):
        service.gifts.action(frame[0], packet["id"], "arm")
    newer = draft(service, frame)
    capable(service, frame)
    with pytest.raises(RevisionConflict, match="out of date"):
        service.gifts.action(frame[0], packet["id"], "arm")
    path = service.gifts.path(newer, "first")
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="integrity"):
        service.gifts.action(frame[0], newer["id"], "arm")
    assert service.gifts.current(frame[0])["status"] == "draft"


def test_authenticated_device_gift_control_and_offline_reveal_report(service, frame):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    client = TestClient(create_app(service, schedule=False))
    auth = {
        "Authorization": "Bearer " + frame[1],
        "X-Emviary-Gift-Version": "1",
        "X-Firmware-Version": "v0.8.12",
    }
    previous = service.store.frame(frame[0])
    response = client.get("/v1/image", headers=auth)
    assert response.status_code == 304 and not response.content
    manifest = json.loads(response.headers["x-emviary-gift"])
    assert manifest["id"] == packet["id"] and manifest["hold_seconds"] == 1800
    assert len(response.headers["x-emviary-gift"]) < 3072
    assert service.store.frame(frame[0])["last_served_etag"] == previous["last_served_etag"]
    for part in ("welcome", "first"):
        url = manifest[part]["url"]
        assert client.get(url).status_code == 401
        delivered = client.get(url, headers=auth)
        assert delivered.status_code == 200
        assert hashlib.sha256(delivered.content).hexdigest() == manifest[part]["sha256"]
        assert delivered.headers["cache-control"] == "private, no-store"
    assert service.gifts.current(frame[0])["status"] == "armed"  # downloads are not display proof
    for state in ("ready", "opened"):
        report = json.dumps({"gift_version": 1, "gift_id": packet["id"], "gift_state": state})
        assert (
            client.get("/v1/gift", headers={**auth, "X-Frame-Metrics": report}).status_code == 200
        )
        assert service.gifts.current(frame[0])["status"] == state
    assert service.gifts.payload(frame[0])["state"] == "none"
    # Stale ready telemetry must never rearm an opened gift.
    service.gifts.observe(
        frame[0], {"gift_version": 1, "gift_id": packet["id"], "gift_state": "ready"}
    )
    assert service.gifts.current(frame[0])["status"] == "opened"


def test_gift_device_ownership_and_corruption_fail_closed(service, frame):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    other = service.store.add_frame("other-frame", service.settings.config.frame_defaults)
    client = TestClient(create_app(service, schedule=False))
    path = f"/v1/gift/{packet['id']}/first"
    assert client.get(path, headers={"Authorization": "Bearer " + other}).status_code == 404
    service.gifts.path(packet, "welcome").write_bytes(b"bad")
    auth = {"Authorization": "Bearer " + frame[1], "X-Emviary-Gift-Version": "1"}
    assert client.get("/v1/gift", headers=auth).status_code == 503
    assert client.get("/v1/image", headers=auth).status_code == 503


def test_gift_owner_csrf_previews_and_calendar_settings_unchanged(
    service, frame, tmp_path, monkeypatch
):
    first = service.prepare(frame[0], offline=True)
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    original = service.store.frame(frame[0])["policy"]
    url = "/manage/frames/" + frame[0] + "/gift"
    data = dict(
        csrf=csrf,
        heading="For my love, Emily.",
        message="A little nature, every day.",
        signature="Love, Luke",
        first_image_id=str(first["id"]),
    )
    for action in ("prepare", "arm", "cancel"):
        assert client.post(url + "/" + action, data={**data, "csrf": "bad"}).status_code == 403
    assert client.post(url + "/prepare", data=data, follow_redirects=False).status_code == 303
    packet = service.gifts.current(frame[0])
    preview = f"{url}/{packet['id']}/preview/welcome"
    assert client.get(preview).status_code == 200
    anon = TestClient(create_app(service, schedule=False))
    assert anon.get(preview).status_code == 401
    page = client.get("/manage/appearance?frame=" + frame[0]).text
    assert "Gift welcome" in page and "Love, Luke" in page and "Show welcome on frame" in page
    capable(service, frame)
    assert (
        client.post(
            url + "/arm", data=dict(csrf=csrf, gift_id=packet["id"]), follow_redirects=False
        ).status_code
        == 303
    )
    assert service.store.frame(frame[0])["policy"] == original
    with pytest.raises(RevisionConflict):
        service.gifts.prepare(frame[0], data)
    assert (
        client.post(
            url + "/cancel",
            data=dict(csrf=csrf, gift_id=packet["id"], expected_state="armed"),
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert service.gifts.payload(frame[0])["state"] == "cancelled"


def test_gift_backup_rehearsal_requires_both_local_images(service, frame, tmp_path):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    backup = Path(service.backup(tmp_path / "gift-backup"))
    assert verify_backup(backup)["frames"] == 1
    (backup / "gifts" / packet["id"] / "first.epdgz").unlink()
    write_manifest(backup)
    (backup / "COMPLETE").write_text(
        json.dumps({"manifest_sha256": file_digest(backup / "integrity-manifest.json")})
    )
    with pytest.raises(ValueError):
        verify_backup(backup)


def test_gift_text_fit_and_telemetry_bounds(service, tmp_path):
    with pytest.raises(ValueError, match="too long|fewer lines"):
        welcome_image(
            service.settings.art_dir,
            dict(heading="W" * 40, message="W" * 80, signature="W" * 30),
            tmp_path / "too-long.png",
        )
    assert (
        parse_metrics(json.dumps({"gift_version": 1, "gift_id": "a" * 32, "gift_state": "ready"}))[
            "gift_version"
        ]
        == 1
    )
    assert (
        parse_metrics(json.dumps({"gift_version": 1, "gift_id": "../bad", "gift_state": "ready"}))
        is None
    )
    assert parse_metrics(json.dumps({"gift_version": 1, "gift_error": "x" * 81})) is None


def test_cancelled_control_cannot_starve_ordinary_art_and_ack_ends_it(service, frame):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    service.gifts.action(frame[0], packet["id"], "cancel", expected_state="armed")
    client = TestClient(create_app(service, schedule=False))
    auth = {"Authorization": "Bearer " + frame[1], "X-Emviary-Gift-Version": "1"}
    normal = client.get("/v1/image", headers=auth)
    assert normal.status_code == 200 and normal.content
    assert json.loads(normal.headers["x-emviary-gift"])["state"] == "cancelled"
    ack = json.dumps(dict(gift_version=1, gift_id=packet["id"], gift_state="cancelled"))
    response = client.get("/v1/gift", headers={**auth, "X-Frame-Metrics": ack})
    assert response.json()["state"] == "none"
    assert service.gifts.current(frame[0])["status"] == "cancelled_done"


def test_preview_error_keeps_edited_message_and_ready_instructions_do_not_reopen(
    service, frame, tmp_path, monkeypatch
):
    first = service.prepare(frame[0], offline=True)
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    url = "/manage/frames/" + frame[0] + "/gift/prepare"
    response = client.post(
        url,
        data=dict(
            csrf=csrf,
            heading="For Emily",
            message="W" * 80,
            signature="W" * 30,
            first_image_id=first["id"],
        ),
    )
    assert response.status_code == 400
    assert 'value="For Emily"' in response.text and 'role="alert"' in response.text
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    service.gifts.observe(frame[0], dict(gift_version=1, gift_id=packet["id"], gift_state="ready"))
    html = client.get("/manage/appearance?frame=" + frame[0]).text
    assert "Update the frame for power-on reveal" in html
    assert "Press the right white button once while online to load" not in html
    overview = client.get("/manage?frame=" + frame[0]).text
    assert f"/gift/{packet['id']}/preview/welcome" in overview
    assert "Gift welcome loaded" in overview


def test_status_refresh_reads_stored_reports_without_device_or_settings_changes(
    service, frame, tmp_path, monkeypatch
):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    client, _ = sign_in(service, tmp_path, monkeypatch)
    url = "/manage/frames/" + frame[0] + "/gift/status"
    before = service.store.frame(frame[0])
    first = client.get(url)
    assert first.json()["state"] == "armed"
    assert first.headers["cache-control"] == "private, no-store"
    assert service.store.frame(frame[0]) == before
    service.gifts.observe(frame[0], dict(gift_version=1, gift_id=packet["id"], gift_state="ready"))
    ready = client.get(url).json()
    assert ready["state"] == "ready" and "Welcome loaded" in ready["html"]
    anon = TestClient(create_app(service, schedule=False))
    assert anon.get(url).status_code == 401


def test_pending_cancellation_cannot_be_hidden_by_a_new_draft(service, frame):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    service.gifts.observe(frame[0], dict(gift_version=1, gift_id=packet["id"], gift_state="ready"))
    service.gifts.action(frame[0], packet["id"], "cancel", expected_state="ready")
    with pytest.raises(RevisionConflict, match="receive cancellation"):
        draft(service, frame)
    service.gifts.observe(frame[0], dict(gift_version=1, gift_id=packet["id"], gift_state="ready"))
    assert service.gifts.payload(frame[0])["state"] == "cancelled"
    assert service.gifts.current(frame[0])["id"] == packet["id"]
    service.gifts.observe(
        frame[0], dict(gift_version=1, gift_id=packet["id"], gift_state="cancelled")
    )
    assert service.gifts.payload(frame[0])["state"] == "none"
    assert draft(service, frame)["id"] != packet["id"]


def test_ready_to_wrap_requires_physical_confirmation_capability_and_device_ack(service, frame):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    report = dict(gift_version=1, gift_id=packet["id"], gift_state="ready")
    service.gifts.observe(frame[0], report)
    with pytest.raises(ValueError, match="Confirm the welcome"):
        service.gifts.action(frame[0], packet["id"], "wrap")
    with pytest.raises(ValueError, match="power-on reveal"):
        service.gifts.action(frame[0], packet["id"], "wrap", True)
    service.store.device_sample(frame[0], {"gift_version": 2}, "v0.8.14")
    original = service.store.frame(frame[0])["policy"]
    service.gifts.action(frame[0], packet["id"], "wrap", True)
    assert service.gifts.current(frame[0])["status"] == "wrap_pending"
    # Repeated ready reports must not erase an unacknowledged wrapping request.
    service.gifts.observe(frame[0], {**report, "gift_version": 2})
    assert service.gifts.current(frame[0])["status"] == "wrap_pending"
    payload = service.gifts.payload(frame[0])
    assert payload == dict(version=1, id=packet["id"], state="wrapped")
    service.gifts.observe(frame[0], {**report, "gift_state": "wrapped"})
    assert service.gifts.current(frame[0])["status"] == "wrap_pending"
    service.gifts.observe(frame[0], {**report, "gift_version": 2, "gift_state": "wrapped"})
    assert service.gifts.current(frame[0])["status"] == "wrapped"
    service.gifts.observe(frame[0], {**report, "gift_version": 2})
    assert service.gifts.current(frame[0])["status"] == "wrapped"
    from emviary.gift_mode import GiftMode

    restarted = GiftMode(service)
    assert restarted.payload(frame[0]) == payload
    service.gifts.observe(frame[0], {**report, "gift_version": 2, "gift_state": "opened"})
    assert service.gifts.current(frame[0])["status"] == "opened"
    assert service.gifts.payload(frame[0])["state"] == "none"
    assert service.store.frame(frame[0])["policy"] == original


def test_wrap_owner_form_requires_checkbox_and_shows_acknowledged_instructions(
    service, frame, tmp_path, monkeypatch
):
    packet = draft(service, frame)
    service.store.device_sample(frame[0], {"gift_version": 2}, "v0.8.14")
    service.gifts.action(frame[0], packet["id"], "arm")
    report = dict(gift_version=2, gift_id=packet["id"], gift_state="ready")
    service.gifts.observe(frame[0], report)
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    url = "/manage/frames/" + frame[0] + "/gift/wrap"
    data = dict(csrf=csrf, gift_id=packet["id"])
    assert client.post(url, data={**data, "csrf": "bad"}).status_code == 403
    assert client.post(url, data=data).status_code == 400
    assert service.gifts.current(frame[0])["status"] == "ready"
    response = client.post(url, data={**data, "welcome_confirmed": "on"})
    assert response.status_code == 200 and "Finishing gift setup" in response.text
    assert "Wait for “Ready to wrap”" in response.text
    service.gifts.observe(frame[0], {**report, "gift_state": "wrapped"})
    html = client.get("/manage/appearance?frame=" + frame[0]).text
    assert "The frame confirmed it is ready" in html
    assert "next power-on reveals" in html and "Ready to wrap</button>" not in html
    assert "next power-on reveals" in client.get("/manage?frame=" + frame[0]).text
    cancel_url = "/manage/frames/" + frame[0] + "/gift/cancel"
    assert 'name="expected_state" value="wrapped"' in html
    assert 'name="cancel_confirmed" required' in html
    for stale in (
        {},
        {"expected_state": "ready"},
        {"expected_state": "wrap_pending", "cancel_confirmed": "on"},
    ):
        assert client.post(cancel_url, data={**data, **stale}).status_code == 409
        assert service.gifts.current(frame[0])["status"] == "wrapped"
    current = {**data, "expected_state": "wrapped"}
    assert client.post(cancel_url, data=current).status_code == 400
    assert service.gifts.current(frame[0])["status"] == "wrapped"
    assert (
        client.post(
            cancel_url, data={**current, "cancel_confirmed": "on"}, follow_redirects=False
        ).status_code
        == 303
    )
    assert service.gifts.payload(frame[0])["state"] == "cancelled"
    with pytest.raises(RevisionConflict):
        draft(service, frame)


def test_ready_to_wrap_rechecks_both_immutable_assets(service, frame):
    packet = draft(service, frame)
    service.store.device_sample(frame[0], {"gift_version": 2}, "v0.8.14")
    service.gifts.action(frame[0], packet["id"], "arm")
    service.gifts.observe(frame[0], dict(gift_version=2, gift_id=packet["id"], gift_state="ready"))
    service.gifts.path(packet, "first").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        service.gifts.action(frame[0], packet["id"], "wrap", True)
    assert service.gifts.current(frame[0])["status"] == "ready"


def test_wrap_control_and_capability_reports_use_authenticated_device_wire(service, frame):
    packet = draft(service, frame)
    client = TestClient(create_app(service, schedule=False))
    auth = {"Authorization": "Bearer " + frame[1], "X-Emviary-Gift-Version": "1"}
    report = dict(gift_version=2, gift_id=packet["id"], gift_state="idle")
    assert (
        client.get("/v1/gift", headers={**auth, "X-Frame-Metrics": json.dumps(report)}).status_code
        == 200
    )
    assert service.gifts.wrap_capable(frame[0])
    service.gifts.action(frame[0], packet["id"], "arm")
    client.get(
        "/v1/gift",
        headers={**auth, "X-Frame-Metrics": json.dumps({**report, "gift_state": "ready"})},
    )
    service.gifts.action(frame[0], packet["id"], "wrap", True)
    before = service.store.frame(frame[0])
    response = client.get("/v1/image", headers=auth)
    assert response.status_code == 304 and not response.content
    assert json.loads(response.headers["x-emviary-gift"]) == dict(
        version=1, id=packet["id"], state="wrapped"
    )
    assert service.store.frame(frame[0])["last_served_etag"] == before["last_served_etag"]
    client.get(
        "/v1/gift",
        headers={**auth, "X-Frame-Metrics": json.dumps({**report, "gift_state": "wrapped"})},
    )
    assert service.gifts.current(frame[0])["status"] == "wrapped"


def test_action_cannot_overwrite_a_device_report_during_submission(service, frame, monkeypatch):
    packet = draft(service, frame)
    capable(service, frame)
    service.gifts.action(frame[0], packet["id"], "arm")
    current = service.gifts.current

    def current_after_device_ack(frame_id):
        snapshot = current(frame_id)
        with service.store.connect() as db:
            db.execute("UPDATE gift_packages SET status='ready' WHERE id=?", (packet["id"],))
        return snapshot

    monkeypatch.setattr(service.gifts, "current", current_after_device_ack)
    with pytest.raises(RevisionConflict):
        service.gifts.action(frame[0], packet["id"], "cancel", expected_state="armed")
    assert current(frame[0])["status"] == "ready"
